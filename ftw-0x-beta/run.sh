#!/usr/bin/env bash
# Supervisor wrapper: prepare /data as root, then hand the process to Core.
set -Eeuo pipefail

readonly runtime_uid=100
readonly runtime_gid=101

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
