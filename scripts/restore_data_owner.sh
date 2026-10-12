#!/usr/bin/env bash
# Run in the stopped app's matching image with only its data mounted at /data.
set -Eeuo pipefail

readonly runtime_uid=100
readonly runtime_gid=101

fail() {
  printf 'FTW data recovery stopped: %s\n' "$*" >&2
  exit 1
}

[[ $# == 0 ]] || fail 'this command takes no arguments'
[[ ${EUID} == 0 ]] || fail 'run this command as root in the recovery container'
[[ -d /data && ! -L /data ]] || fail '/data must be a directory, not a link'
[[ "$(realpath -e -- /data)" == /data ]] || fail '/data must be the mounted app data'

# A bind mount can share the parent's device number. Check mountpoints as well
# as using find -xdev, before any owner changes.
if ! awk '$5 ~ /^\/data\// { found=1 } END { exit found }' /proc/self/mountinfo; then
  fail '/data contains a nested mount; keep it outside this recovery'
fi
[[ -z "$(find -P /data -xdev -type f -links +1 -printf x -quit)" ]] ||
  fail '/data contains a hard link; preserve it and check its source first'

links=$(mktemp)
trap 'rm -f -- "$links"' EXIT
find -P /data -xdev -type l -print0 >"${links}"
while IFS= read -r -d '' link; do
  target=$(realpath -e -- "${link}" 2>/dev/null) || fail '/data contains a broken or cyclic link'
  case "${target}" in
    /data|/data/*) ;;
    *) fail '/data contains a link to files outside the app data' ;;
  esac
done <"${links}"

# Never follow links, and preserve every file's mode and bytes. The app stays
# stopped: this command changes only ownership and does not launch Core.
find -P /data -xdev -exec chown --no-dereference -- "${runtime_uid}:${runtime_gid}" {} +
printf 'FTW data ownership restored to uid %s, gid %s; Core remains stopped.\n' \
  "${runtime_uid}" "${runtime_gid}"
