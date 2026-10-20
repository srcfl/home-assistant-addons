#!/usr/bin/env bash
# Supervisor wrapper: prepare /data as root, then hand the process to Core.
set -Eeuo pipefail

readonly runtime_uid=100
readonly runtime_gid=101

fail() { printf 'FTW data preparation stopped: %s\n' "$*" >&2; exit 1; }

for dir in /data /data/drivers /data/driver-repository; do
  [[ ! -L "${dir}" ]] || fail "${dir} must not be a link"
done

# Supervisor's securetar restore writes files as root, with mode 0644.
# Repair a restored data tree before dropping privileges. A normal boot does
# not walk history. Refuse nested mounts and hard links before changing owners;
# find -P and chown --no-dereference never follow symbolic links.
for file in config.yaml state.db history.db applink.json nova.key webpush.key; do
  if [[ -f "/data/${file}" && ! -L "/data/${file}" ]] && \
    [[ "$(stat -c %u "/data/${file}")" == 0 ]]; then
    if ! awk '$5 ~ /^\/data\// { found=1 } END { exit found }' /proc/self/mountinfo; then
      fail '/data contains a nested mount'
    fi
    [[ -z "$(find -P /data -xdev -type f -links +1 -printf x -quit)" ]] || \
      fail '/data contains a hard link'
    find -P /data -xdev -exec chown --no-dereference -- "${runtime_uid}:${runtime_gid}" {} +
    printf 'FTW: restored data ownership to %s:%s\n' "${runtime_uid}" "${runtime_gid}"
    break
  fi
done

# Settings, keys and databases contain credentials. Do not follow links or
# alter history files below /data while restoring these top-level modes.
find -P /data -maxdepth 1 -type f \( -name config.yaml -o -name '*.key' \
  -o -name applink.json -o -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' \) \
  -exec chmod 0600 -- {} +

install -d -o "${runtime_uid}" -g "${runtime_gid}" -m 0750 \
  /data /data/drivers /data/driver-repository

# These values also exist in config.yaml and the image. Export them here so an
# injected environment cannot turn self-update on or make Core present itself
# as anything but the Home Assistant bundle.
export FTW_SELFUPDATE_ENABLED=0
export FTW_BUNDLE=home_assistant_addon

exec setpriv --reuid="${runtime_uid}" --regid="${runtime_gid}" --clear-groups -- \
  /app/ftw \
  -config /data/config.yaml \
  -web /app/web \
  -drivers /app/drivers \
  -user-drivers /data/drivers
