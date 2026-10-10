#!/usr/bin/env bash
# Included in a verified deployment archive before the preserved release script.
# This creates swap on the root filesystem only, never on the retained data disk.
set +x
set -Eeuo pipefail
(
  set -Eeuo pipefail
  umask 077
  economy_die() { printf 'routewise economy preparation: %s\n' "$*" >&2; exit 1; }
  [[ $EUID -eq 0 ]] || economy_die 'Run as root.'
  for economy_command in flock install stat readlink findmnt df awk mktemp dd \
    mkswap blkid swapon sysctl jq ln rm chmod; do
    command -v "$economy_command" >/dev/null || economy_die "Missing prerequisite: $economy_command"
  done
  # Reject direct execution from an arbitrary path or a mismatched release.
  economy_release=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
  [[ $economy_release =~ ^/opt/routewise/releases/[0-9a-f]{40}$ ]] \
    || economy_die 'Unexpected release directory.'
  [[ -f $economy_release/release.json && ! -L $economy_release/release.json ]] \
    || economy_die 'A regular release manifest is required.'
  economy_commit=$(jq -er '.commit | select(type == "string")' "$economy_release/release.json")
  [[ $economy_commit =~ ^[0-9a-f]{40}$ && $economy_release == "/opt/routewise/releases/$economy_commit" ]] \
    || economy_die 'The release directory and manifest do not match.'
  [[ ${AWS_REGION:-} == us-east-1 ]] || economy_die 'Unexpected AWS_REGION.'
  [[ ${DATA_VOLUME_ID:-} =~ ^vol-([0-9a-f]{8}|[0-9a-f]{17})$ ]] \
    || economy_die 'Invalid DATA_VOLUME_ID.'
  [[ $# -le 1 && ( -z ${1:-} || $1 == "$DATA_VOLUME_ID" ) ]] \
    || economy_die 'Conflicting data volume argument.'

  # Descriptor 8 is closed on leaving this subshell. It cannot replace the
  # original release/download/backup lock held on descriptor 9.
  exec 8>/run/lock/routewise-economy-host.lock
  flock -w 600 8 || economy_die 'Another host preparation still owns the lock.'
  economy_swap_dir=/var/lib/routewise
  economy_swap_file=/var/lib/routewise/economy.swap
  economy_swap_bytes=2147483648
  for economy_parent in /var /var/lib; do
    [[ -d $economy_parent && ! -L $economy_parent ]] \
      || economy_die 'The swap parent must be a regular directory.'
  done
  [[ ! -L $economy_swap_dir ]] || economy_die 'The swap directory must not be a symlink.'
  if [[ -e $economy_swap_dir ]]; then
    [[ -d $economy_swap_dir && $(stat -c '%u:%g:%a' "$economy_swap_dir") == 0:0:700 ]] \
      || economy_die 'The existing swap directory must be root-owned with mode 700.'
  else
    install -d -o root -g root -m 0700 "$economy_swap_dir"
  fi
  [[ $(findmnt -nro SOURCE --target "$economy_swap_dir") == "$(findmnt -nro SOURCE --target /)" ]] \
    || economy_die 'Swap must be on the root filesystem, not a mounted data volume.'
  [[ -f /etc/fstab && ! -L /etc/fstab && $(stat -c '%u' /etc/fstab) == 0 ]] \
    || economy_die 'A root-owned regular fstab is required.'
  mapfile -t economy_fstab_entries < <(
    awk -v path="$economy_swap_file" '$1 !~ /^#/ && $1 == path { print $0 }' /etc/fstab
  )
  [[ ${#economy_fstab_entries[@]} -le 1 ]] \
    || economy_die 'Duplicate swap entries require manual review.'
  if [[ ${#economy_fstab_entries[@]} -eq 1 ]]; then
    [[ $(awk -v path="$economy_swap_file" \
      '$1 == path && $2 == "none" && $3 == "swap" && $4 == "sw,nofail" && $5 == 0 && $6 == 0 { print "valid" }' \
      /etc/fstab) == valid ]] || economy_die 'An incompatible swap fstab entry already exists.'
  fi
  economy_sysctl=/etc/sysctl.d/90-routewise-economy.conf
  [[ -d /etc/sysctl.d && ! -L /etc/sysctl.d ]] \
    || economy_die 'The sysctl directory must not be a symlink.'
  if [[ -e $economy_sysctl || -L $economy_sysctl ]]; then
    [[ -f $economy_sysctl && ! -L $economy_sysctl && $(stat -c '%u:%g:%a' "$economy_sysctl") == 0:0:644 ]] \
      || economy_die 'The existing economy sysctl file must be root-owned with mode 644.'
    [[ $(<"$economy_sysctl") == 'vm.swappiness=10' ]] \
      || economy_die 'The existing economy sysctl configuration requires manual review.'
  fi

  if [[ -e $economy_swap_file || -L $economy_swap_file ]]; then
    # Never truncate, reformat, replace or change permissions on an unknown file.
    [[ -f $economy_swap_file && ! -L $economy_swap_file ]] \
      || economy_die 'The existing swap path must be a regular file.'
    [[ $(stat -c '%u:%g:%a:%h' "$economy_swap_file") == 0:0:600:1 ]] \
      || economy_die 'The existing swap file must be root-owned, mode 600, with one link.'
    [[ $(stat -c '%s' "$economy_swap_file") == "$economy_swap_bytes" ]] \
      || economy_die 'The existing swap file is not exactly 2 GiB.'
    [[ $(blkid -p -s TYPE -o value "$economy_swap_file" 2>/dev/null) == swap ]] \
      || economy_die 'The existing file has no valid swap signature; nothing was formatted.'
  else
    economy_available=$(df --block-size=1 --output=avail "$economy_swap_dir" | awk 'NR == 2 {print $1}')
    [[ $economy_available =~ ^[0-9]+$ && $economy_available -ge 3221225472 ]] \
      || economy_die 'At least 3 GiB free on the root disk is required before creating 2 GiB swap.'
    economy_temporary=$(mktemp "$economy_swap_dir/.economy-swap.XXXXXXXX")
    economy_cleanup() { [[ -z ${economy_temporary:-} ]] || rm -f -- "$economy_temporary"; }
    trap economy_cleanup EXIT
    # Fully write the private new file. Sparse swap files cannot be activated.
    dd if=/dev/zero of="$economy_temporary" bs=1M count=2048 conv=fsync status=none
    [[ $(stat -c '%u:%g:%a:%s' "$economy_temporary") == 0:0:600:2147483648 ]] \
      || economy_die 'New swap file verification failed.'
    mkswap -L routewise-swap "$economy_temporary" >/dev/null
    # A hard-link publication fails if a file appeared at the final path.
    # Neither existing files nor a partially initialized file are overwritten.
    ln -- "$economy_temporary" "$economy_swap_file"
    rm -f -- "$economy_temporary"
    economy_temporary=''
    trap - EXIT
  fi
  if ! swapon --show=NAME --noheadings --raw | awk -v path="$economy_swap_file" \
      '$0 == path {found=1} END {exit !found}'; then
    swapon -- "$economy_swap_file"
  fi
  [[ ${#economy_fstab_entries[@]} -ne 0 ]] || \
    printf '%s none swap sw,nofail 0 0\n' "$economy_swap_file" >>/etc/fstab
  if [[ ! -e $economy_sysctl ]]; then
    ( set -o noclobber; printf 'vm.swappiness=10\n' >"$economy_sysctl" )
    chmod 0644 "$economy_sysctl"
  fi
  sysctl -q -w vm.swappiness=10
  printf 'Economy host preparation complete: validated 2 GiB root-disk swap.\n'
)
