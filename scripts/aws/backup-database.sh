#!/usr/bin/env bash
# Run as root. S3 lifecycle retention is configured by the CloudFormation stack.
set +x
set -Eeuo pipefail
umask 077
export AWS_PAGER=""
export AWS_RETRY_MODE=standard
export AWS_MAX_ATTEMPTS=5

die() { printf 'RouteWise backup: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die 'Run this script as root.'
[[ $# -le 1 ]] || die 'Usage: backup-database.sh [--deployment-lock-held]'
if [[ ${1:-} == --deployment-lock-held ]]; then
  # Only deploy-release.sh uses this option while it holds the inherited lock.
  [[ -e /proc/$$/fd/9 ]] || die 'The deployment lock descriptor is missing.'
  flock -n 9 || die 'The inherited deployment lock is unavailable.'
elif [[ $# -eq 0 ]]; then
  exec 9>/run/lock/routewise-deploy.lock
  flock -w 600 9 || die 'Another deployment or backup still owns the lock.'
else
  die 'Unknown argument.'
fi

data_dir=/srv/routewise
env_file=$data_dir/runtime.env
[[ -f $env_file && ! -L $env_file ]] || die 'The runtime environment is missing.'
[[ $(stat -c '%u:%a' "$env_file") == 0:600 ]] || die 'runtime.env must be owned by root with mode 600.'
# This file is generated exclusively by deploy-release.sh from validated values.
# shellcheck disable=SC1090
source "$env_file"
[[ ${DATA_VOLUME_ID:-} =~ ^vol-([0-9a-f]{8}|[0-9a-f]{17})$ ]] || die 'Invalid volume ID.'
[[ ${AWS_REGION:-} =~ ^[a-z]{2}(-[a-z]+)+-[0-9]+$ ]] || die 'Invalid AWS region.'
[[ ${BACKUP_BUCKET:-} =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die 'Invalid backup bucket.'
mountpoint -q "$data_dir" || die 'The data volume is not mounted.'
mounted_device=$(findmnt -nro SOURCE --target "$data_dir")
mounted_serial=$(lsblk -dnro SERIAL "$mounted_device" | tr -d '[:space:]-')
[[ $mounted_serial == "${DATA_VOLUME_ID//-/}" ]] || die 'The mounted volume does not match DATA_VOLUME_ID.'

release_dir=${ROUTEWISE_BACKUP_RELEASE_DIR:-$(readlink -f /opt/routewise/current)}
[[ $release_dir =~ ^/opt/routewise/releases/[0-9a-f]{40}$ ]] || die 'Invalid release directory.'
compose_file=$release_dir/infra/aws/compose.yaml
[[ -f $compose_file && ! -L $compose_file ]] || die 'The release Compose file is missing.'
compose=(docker compose --project-name routewise-prod --env-file "$env_file" --file "$compose_file")
[[ -f $data_dir/postgres/PG_VERSION ]] || die 'No initialized database exists.'
[[ -d $data_dir/backups && ! -L $data_dir/backups ]] || die 'The backup directory is missing or unsafe.'
dump_file=$(mktemp "$data_dir/backups/.backup.XXXXXXXX")
trap 'rm -f -- "$dump_file"' EXIT

# pg_dump runs inside the existing PostgreSQL container, with no password in
# process arguments. A custom archive provides a consistent logical backup.
timeout 600 "${compose[@]}" exec -T postgres \
  pg_dump --username=routewise --dbname=routewise --format=custom \
  --compress=6 --no-owner --no-acl >"$dump_file" 2>/dev/null \
  || die 'Database export failed; the existing deployment was left intact.'
[[ -s $dump_file ]] || die 'Database export was empty.'
timeout 60 "${compose[@]}" exec -T postgres pg_restore --list \
  <"$dump_file" >/dev/null 2>&1 || die 'The exported archive could not be read.'
backup_key="postgres/$(date -u +%Y/%m/%d)/$(date -u +%Y%m%dT%H%M%S%NZ)-${release_dir##*/}.dump"
timeout 600 aws s3 cp "$dump_file" "s3://$BACKUP_BUCKET/$backup_key" \
  --region "$AWS_REGION" --sse AES256 --only-show-errors >/dev/null 2>&1 \
  || die 'The archive could not be uploaded to S3.'
# Record only non-secret recovery metadata. No completed dump stays on disk.
printf '%s\n' "s3://$BACKUP_BUCKET/$backup_key" >"$data_dir/last-backup.txt"
printf 'RouteWise backup uploaded successfully.\n'
