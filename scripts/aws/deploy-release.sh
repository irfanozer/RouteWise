#!/usr/bin/env bash
# Contract: execute the verified archive's script as root from
# /opt/routewise/releases/<full-commit>/scripts/aws/deploy-release.sh.
# Required environment: AWS_REGION, DATA_VOLUME_ID, BACKUP_BUCKET, ORIGIN_DOMAIN.
# PUBLIC_ORIGIN optionally contains comma-separated HTTPS viewer origins.
# An optional first argument can supply DATA_VOLUME_ID; conflicting IDs fail.
# This script never restores a database or attempts an automatic schema rollback.
# Retained releases and previous.env support an operator-selected rollback ONLY
# when the previous application is compatible with the current database schema.
set +x
set -Eeuo pipefail
umask 077
export AWS_PAGER=""
export AWS_RETRY_MODE=standard
export AWS_MAX_ATTEMPTS=5

die() { printf 'RouteWise deployment: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die 'Run this script as root.'
[[ $# -le 1 ]] || die 'Usage: deploy-release.sh [DATA_VOLUME_ID]'
[[ -z ${1:-} || -z ${DATA_VOLUME_ID:-} || $1 == "$DATA_VOLUME_ID" ]] \
  || die 'The argument and environment specify different data volumes.'
DATA_VOLUME_ID=${1:-${DATA_VOLUME_ID:-}}
[[ $DATA_VOLUME_ID =~ ^vol-([0-9a-f]{8}|[0-9a-f]{17})$ ]] || die 'Invalid DATA_VOLUME_ID.'
[[ ${AWS_REGION:-} =~ ^[a-z]{2}(-[a-z]+)+-[0-9]+$ ]] || die 'Invalid AWS_REGION.'
[[ ${BACKUP_BUCKET:-} =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die 'Invalid BACKUP_BUCKET.'
[[ ${ORIGIN_DOMAIN:-} =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] \
  || die 'ORIGIN_DOMAIN must be a lowercase DNS hostname without a scheme.'
[[ ${#ORIGIN_DOMAIN} -le 253 ]] || die 'The origin hostname is too long.'

for command in aws docker jq flock lsblk blkid wipefs findmnt mount mountpoint \
  mkfs.ext4 blockdev install readlink stat timeout systemctl; do
  command -v "$command" >/dev/null || die "Missing prerequisite: $command"
done
docker compose version >/dev/null 2>&1 || die 'Docker Compose v2 is required.'
exec 9>/run/lock/routewise-deploy.lock
flock -w 600 9 || die 'Another deployment or backup still owns the lock.'

release_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
[[ $release_dir =~ ^/opt/routewise/releases/[0-9a-f]{40}$ ]] || die 'Unexpected release directory.'
for relative_file in release.json infra/aws/compose.yaml infra/aws/Caddyfile infra/aws/api-proxy.conf \
  scripts/aws/deploy-release.sh scripts/aws/backup-database.sh; do
  [[ -f $release_dir/$relative_file && ! -L $release_dir/$relative_file ]] \
    || die "A regular release file is required: $relative_file"
done
commit=$(jq -er '.commit | select(type == "string")' "$release_dir/release.json")
backend_image=$(jq -er '.backend_image | select(type == "string")' "$release_dir/release.json")
[[ $commit =~ ^[0-9a-f]{40}$ && $release_dir == "/opt/routewise/releases/$commit" ]] \
  || die 'The release directory and full commit do not match.'
[[ $backend_image =~ ^ghcr\.io/irfanozer/routewise-backend@sha256:[0-9a-f]{64}$ ]] \
  || die 'The backend image must use the approved repository and an immutable digest.'

public_origins=${PUBLIC_ORIGIN:-}
cors_origins='[]'
if [[ -n $public_origins ]]; then
  IFS=',' read -r -a viewer_origins <<<"$public_origins"
  for viewer_origin in "${viewer_origins[@]}"; do
    [[ $viewer_origin =~ ^https://([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] \
      || die 'PUBLIC_ORIGIN must contain only comma-separated HTTPS origins, without paths.'
  done
  [[ $public_origins != *, ]] || die 'PUBLIC_ORIGIN contains an empty origin.'
  cors_origins=$(printf '%s' "$public_origins" | jq -Rc 'split(",") | unique')
fi

data_dir=/srv/routewise
expected_serial=${DATA_VOLUME_ID//-/}
device=''
# Nitro device names can change on every boot. Match the EBS identity, never
# /dev/nvme1n1 or the requested /dev/sdf attachment name by assumption.
for ((attempt = 1; attempt <= 30; attempt++)); do
  by_id="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_$expected_serial"
  if [[ -L $by_id ]]; then
    device=$(readlink -f "$by_id")
  else
    mapfile -t matching_devices < <(lsblk -dpnro NAME,SERIAL | awk -v serial="$expected_serial" \
      '{candidate=$2; gsub(/-/, "", candidate); if (candidate == serial) print $1}')
    [[ ${#matching_devices[@]} -le 1 ]] || die 'More than one block device matches the EBS volume.'
    device=${matching_devices[0]:-}
  fi
  [[ -n $device && -b $device ]] && break
  sleep 2
done
[[ -n $device && -b $device ]] || die 'The requested EBS data volume did not appear.'
actual_serial=$(lsblk -dnro SERIAL "$device" | tr -d '[:space:]-')
[[ $actual_serial == "$expected_serial" ]] || die 'The block device serial does not match DATA_VOLUME_ID.'
[[ $(lsblk -dnro TYPE "$device") == disk ]] || die 'A whole EBS data disk is required.'
[[ $(lsblk -nr -o NAME "$device" | wc -l) -eq 1 ]] || die 'Partitioned volumes require manual review; nothing was formatted.'
[[ $(blockdev --getro "$device") == 0 ]] || die 'The data disk is read-only.'
# Reject another mounted filesystem, including the root disk, before probing.
while IFS= read -r existing_mount; do
  [[ -z $existing_mount || $existing_mount == "$data_dir" ]] \
    || die 'The requested data disk is mounted somewhere else; nothing was formatted.'
done < <(lsblk -dnro MOUNTPOINTS "$device")

filesystem=$(blkid -p -s TYPE -o value "$device" 2>/dev/null || true)
if [[ -z $filesystem ]]; then
  probe_status=0
  blkid -p "$device" >/dev/null 2>&1 || probe_status=$?
  [[ $probe_status -eq 2 ]] || die 'An existing or ambiguous disk signature requires manual review.'
  signatures=$(wipefs --no-act --noheadings --output TYPE "$device")
  [[ -z $signatures ]] || die 'Existing disk signatures were found; nothing was formatted.'
  [[ -z $(lsblk -dnro MOUNTPOINTS "$device") ]] || die 'A mounted disk must never be formatted.'
  # Only the explicitly matched, unmounted EBS disk with no filesystem,
  # partitions, or recognized signatures can enter this initialization branch.
  mkfs.ext4 -q "$device" >/dev/null 2>&1 || die 'Could not initialize the new EBS data volume.'
  filesystem=ext4
fi
[[ $filesystem == ext4 || $filesystem == xfs ]] \
  || die 'The existing filesystem is not ext4 or XFS; nothing was formatted.'
filesystem_uuid=$(blkid -s UUID -o value "$device")
[[ $filesystem_uuid =~ ^[0-9a-fA-F-]+$ ]] || die 'The data filesystem has no valid UUID.'
[[ ! -L $data_dir ]] || die 'The data directory must not be a symlink.'
install -d -m 0700 "$data_dir"
if mountpoint -q "$data_dir"; then
  [[ $(findmnt -nro UUID --target "$data_dir") == "$filesystem_uuid" ]] \
    || die 'A different filesystem is mounted at the data directory.'
else
  [[ -z $(find "$data_dir" -mindepth 1 -maxdepth 1 -print -quit) ]] \
    || die 'The unmounted data directory contains files; manual recovery is required.'
fi
mapfile -t fstab_sources < <(awk '$1 !~ /^#/ && $2 == "/srv/routewise" {print $1}' /etc/fstab)
if [[ ${#fstab_sources[@]} -eq 0 ]]; then
  fsck_pass=0
  [[ $filesystem != ext4 ]] || fsck_pass=2
  printf 'UUID=%s /srv/routewise %s defaults,nosuid,nodev 0 %s\n' \
    "$filesystem_uuid" "$filesystem" "$fsck_pass" >>/etc/fstab
else
  [[ ${#fstab_sources[@]} -eq 1 && ${fstab_sources[0]} == "UUID=$filesystem_uuid" ]] \
    || die 'An incompatible fstab entry already exists for the data directory.'
fi
systemctl daemon-reload
mountpoint -q "$data_dir" || mount "$data_dir"
[[ $(findmnt -nro UUID --target "$data_dir") == "$filesystem_uuid" ]] || die 'Mounted data volume verification failed.'
chmod 0700 "$data_dir"

# Docker must not start bind-mounted services on an empty root-disk directory
# if the retained EBS data volume is absent during a future boot.
install -d -m 0755 /etc/systemd/system/docker.service.d
printf '[Unit]\nRequiresMountsFor=/srv/routewise\n' \
  >/etc/systemd/system/docker.service.d/routewise-storage.conf
systemctl daemon-reload
systemctl start docker
for relative_dir in postgres caddy caddy/data caddy/config backups deployments; do
  [[ ! -L $data_dir/$relative_dir ]] || die 'A runtime directory must not be a symlink.'
  [[ -d $data_dir/$relative_dir ]] || install -d -m 0700 "$data_dir/$relative_dir"
done
env_file=$data_dir/runtime.env
[[ ! -L $env_file ]] || die 'runtime.env must not be a symlink.'
database_exists=false
if [[ -f $data_dir/postgres/PG_VERSION ]]; then
  [[ $(<"$data_dir/postgres/PG_VERSION") == 17 ]] || die 'Only PostgreSQL 17 data directories are supported.'
  database_exists=true
  [[ -f $env_file ]] || die 'The existing database has no runtime.env; recover its configuration first.'
elif [[ -n $(find "$data_dir/postgres" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
  die 'The data directory is nonempty but has no PG_VERSION; manual recovery is required.'
fi
if [[ -e $env_file ]]; then
  [[ -f $env_file && $(stat -c '%u:%a' "$env_file") == 0:600 ]] \
    || die 'runtime.env must be a root-owned regular file with mode 600.'
fi

database_password=$(aws ssm get-parameter --region "$AWS_REGION" \
  --cli-connect-timeout 5 --cli-read-timeout 20 \
  --name /routewise/prod/database-password --with-decryption \
  --query Parameter.Value --output text 2>/dev/null) || die 'Database secret could not be read from SSM.'
origin_token=$(aws ssm get-parameter --region "$AWS_REGION" \
  --cli-connect-timeout 5 --cli-read-timeout 20 \
  --name /routewise/prod/origin-token --with-decryption \
  --query Parameter.Value --output text 2>/dev/null) || die 'Origin secret could not be read from SSM.'
[[ $database_password =~ ^([0-9a-fA-F]{32}|[0-9a-fA-F]{64})$ ]] \
  || die 'The database secret must be 32 or 64 hex characters.'
[[ $origin_token =~ ^([0-9a-fA-F]{32}|[0-9a-fA-F]{64})$ ]] \
  || die 'The origin secret must be 32 or 64 hex characters.'
if [[ -f $env_file ]]; then
  previous_password=$(sed -n 's/^POSTGRES_PASSWORD=//p' "$env_file")
  [[ $previous_password == "$database_password" ]] \
    || die 'The database password changed; complete an explicit database password rotation before deploying.'
  unset previous_password
fi

deployment_dir=$data_dir/deployments/$(date -u +%Y%m%dT%H%M%S%NZ)-$commit
install -d -m 0700 "$deployment_dir"
[[ ! -f $env_file ]] || install -m 0600 "$env_file" "$deployment_dir/previous.env"
previous_release=''
if [[ -e /opt/routewise/current || -L /opt/routewise/current ]]; then
  previous_release=$(readlink -f /opt/routewise/current 2>/dev/null || true)
  [[ -L /opt/routewise/current && -d $previous_release && $previous_release =~ ^/opt/routewise/releases/[0-9a-f]{40}$ ]] \
    || die 'The current release pointer is invalid.'
  printf '%s\n' "$previous_release" >"$deployment_dir/previous-release.txt"
fi
candidate_env=$(mktemp "$data_dir/.runtime.XXXXXXXX")
stage=validation
on_exit() {
  status=$?
  rm -f -- "$candidate_env"
  if [[ $status -ne 0 ]]; then
    printf 'failed during %s\n' "$stage" >"$deployment_dir/status.txt"
    printf 'Deployment failed during %s. Recovery metadata: %s. No automatic database rollback was attempted.\n' \
      "$stage" "$deployment_dir" >&2
  fi
}
trap on_exit EXIT
{
  printf 'AWS_REGION=%s\nDATA_VOLUME_ID=%s\nBACKUP_BUCKET=%s\n' "$AWS_REGION" "$DATA_VOLUME_ID" "$BACKUP_BUCKET"
  printf 'ORIGIN_DOMAIN=%s\nPUBLIC_ORIGIN=%s\n' "$ORIGIN_DOMAIN" "$public_origins"
  printf 'BACKEND_IMAGE=%s\nPOSTGRES_PASSWORD=%s\nORIGIN_VERIFY_TOKEN=%s\n' "$backend_image" "$database_password" "$origin_token"
  printf "ROUTEWISE_CORS_ORIGINS='%s'\n" "$cors_origins"
} >"$candidate_env"
unset database_password origin_token
# Compose prioritizes inherited environment variables over --env-file. Require
# the validated candidate values even if the invoking process exported these.
unset BACKEND_IMAGE POSTGRES_PASSWORD ORIGIN_VERIFY_TOKEN ROUTEWISE_CORS_ORIGINS
compose=(docker compose --project-name routewise-prod --env-file "$candidate_env" --file "$release_dir/infra/aws/compose.yaml")
# Never print rendered Compose configuration: it contains decrypted secrets.
"${compose[@]}" config --quiet >/dev/null 2>&1 || die 'The Compose configuration is invalid.'
stage=image-pull
timeout 600 "${compose[@]}" pull postgres backend api-proxy caddy >/dev/null 2>&1 || die 'An image could not be pulled.'
timeout 60 "${compose[@]}" run --rm --no-deps caddy \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
  || die 'The Caddy configuration is invalid.'
timeout 60 "${compose[@]}" run --rm --no-deps api-proxy -t >/dev/null 2>&1 \
  || die 'The Nginx API proxy configuration is invalid.'

if [[ $database_exists == true ]]; then
  stage=pre-deployment-backup
  # Keep an existing PostgreSQL container intact until its backup is uploaded.
  docker compose --project-name routewise-prod --env-file "$env_file" \
    --file "$release_dir/infra/aws/compose.yaml" up --detach --no-recreate \
    --wait --wait-timeout 120 postgres >/dev/null 2>&1 || die 'The existing database did not become ready.'
  ROUTEWISE_BACKUP_RELEASE_DIR="$release_dir" \
    bash "$release_dir/scripts/aws/backup-database.sh" --deployment-lock-held \
    || die 'The mandatory pre-deployment backup failed; no migration was run.'
fi

stage=database-start
# Both files live on the same EBS filesystem, so readers see a complete config.
chmod 0600 "$candidate_env"
mv -Tf "$candidate_env" "$env_file"
compose=(docker compose --project-name routewise-prod --env-file "$env_file" --file "$release_dir/infra/aws/compose.yaml")
"${compose[@]}" up --detach --wait --wait-timeout 120 postgres >/dev/null 2>&1 \
  || die 'PostgreSQL did not become ready.'
stage=migration
"${compose[@]}" stop --timeout 30 backend >/dev/null 2>&1 || die 'The previous backend could not be stopped.'
timeout 300 "${compose[@]}" run --rm --no-deps migrate >/dev/null 2>&1 \
  || die 'Database migration failed; inspect the database before choosing a compatible release.'
printf 'migration completed\n' >"$deployment_dir/status.txt"
stage=local-readiness
"${compose[@]}" up --detach --wait --wait-timeout 180 postgres backend api-proxy caddy >/dev/null 2>&1 \
  || die 'The new containers did not become healthy; select a rollback only after checking schema compatibility.'
"${compose[@]}" exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)" \
  >/dev/null 2>&1 || die 'The backend readiness request failed.'

stage=release-metadata
if [[ -n $previous_release && $previous_release != "$release_dir" ]]; then
  ln -sfnT "$previous_release" /opt/routewise/previous.next
  mv -Tf /opt/routewise/previous.next /opt/routewise/previous
fi
ln -sfnT "$release_dir" /opt/routewise/current.next
mv -Tf /opt/routewise/current.next /opt/routewise/current

# A daily backup shares the deployment lock, and catches up after a stopped VM.
printf '%s\n' \
  '[Unit]' 'Description=RouteWise encrypted S3 database backup' \
  'Requires=docker.service' 'After=docker.service network-online.target' \
  'Wants=network-online.target' 'RequiresMountsFor=/srv/routewise' \
  '[Service]' 'Type=oneshot' 'User=root' 'UMask=0077' \
  'ExecStart=/bin/bash /opt/routewise/current/scripts/aws/backup-database.sh' \
  'TimeoutStartSec=25min' \
  >/etc/systemd/system/routewise-backup.service
printf '%s\n' '[Unit]' 'Description=Daily RouteWise database backup' \
  '[Timer]' 'OnCalendar=*-*-* 04:15:00 UTC' 'RandomizedDelaySec=15min' \
  'Persistent=true' '[Install]' 'WantedBy=timers.target' \
  >/etc/systemd/system/routewise-backup.timer
systemctl daemon-reload
systemctl enable --now routewise-backup.timer >/dev/null 2>&1
printf 'locally ready; CloudFront smoke check pending\n' >"$deployment_dir/status.txt"
printf 'Release %s is locally ready. Complete the public HTTPS CloudFront smoke check before marking production healthy.\n' "$commit"
