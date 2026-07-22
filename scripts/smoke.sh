#!/usr/bin/env bash
set -Eeuo pipefail

image=${1:?usage: smoke.sh IMAGE}
name="ftw-ha-smoke-${RANDOM}"
volume="ftw-ha-data-${RANDOM}"

cleanup() {
  docker rm -f "${name}" >/dev/null 2>&1 || true
  docker volume rm "${volume}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for_optimizer() {
  for _ in {1..120}; do
    if docker exec "${name}" /opt/venv/bin/ftw-optimizer-healthcheck >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  docker logs "${name}" >&2
  return 1
}

docker volume create "${volume}" >/dev/null
docker run -d --name "${name}" --volume "${volume}:/data" "${image}" >/dev/null

for _ in {1..60}; do
  if [[ "$(docker inspect --format '{{.State.Health.Status}}' "${name}")" == healthy ]]; then
    break
  fi
  sleep 1
done
[[ "$(docker inspect --format '{{.State.Health.Status}}' "${name}")" == healthy ]]

wait_for_optimizer
docker exec "${name}" bash -ceu 'test "$FTW_SELFUPDATE_ENABLED" = 0; test "$FTW_OPTIMIZER_TRANSPORT" = unix'
docker exec "${name}" bash -ceu 'install -d -o 100 -g 101 /data/drivers; printf "%s\n" "-- user marker" >/data/drivers/custom.lua; : >/data/config.yaml; chown 100:101 /data/config.yaml /data/drivers/custom.lua'
docker exec "${name}" /usr/local/bin/healthcheck.py

old_optimizer_pid="$(docker exec "${name}" bash -ceu 'cat /run/ftw-optimizer/worker.pid')"
docker exec "${name}" bash -ceu 'kill -TERM "$1"' -- "${old_optimizer_pid}"
docker exec "${name}" /usr/local/bin/healthcheck.py
for _ in {1..70}; do
  new_optimizer_pid="$(docker exec "${name}" bash -ceu 'cat /run/ftw-optimizer/worker.pid 2>/dev/null || true')"
  if [[ -n "${new_optimizer_pid}" && "${new_optimizer_pid}" != "${old_optimizer_pid}" ]]; then
    break
  fi
  sleep 1
done
[[ -n "${new_optimizer_pid}" && "${new_optimizer_pid}" != "${old_optimizer_pid}" ]]
wait_for_optimizer
docker exec "${name}" /usr/local/bin/healthcheck.py

docker stop --time 20 "${name}" >/dev/null
[[ "$(docker inspect --format '{{.State.ExitCode}}' "${name}")" == 0 ]]
docker rm "${name}" >/dev/null

docker run -d --name "${name}" --volume "${volume}:/data" "${image}" >/dev/null
for _ in {1..60}; do
  if docker exec "${name}" /usr/local/bin/healthcheck.py >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${name}" /usr/local/bin/healthcheck.py
docker exec "${name}" grep -Fx -- '-- user marker' /data/drivers/custom.lua
if docker exec "${name}" bash -ceu \
  'for process in /proc/[0-9]*/cmdline; do tr "\0" " " <"${process}"; printf "\n"; done' \
  | grep -q ftw-updater; then
  printf '%s\n' "unexpected FTW updater process" >&2
  exit 1
fi

core_pid="$(docker exec "${name}" bash -ceu 'cat /run/ftw/core.pid')"
docker exec "${name}" bash -ceu 'kill -KILL "$1"' -- "${core_pid}"
for _ in {1..30}; do
  if [[ "$(docker inspect --format '{{.State.Running}}' "${name}")" == false ]]; then
    break
  fi
  sleep 1
done
[[ "$(docker inspect --format '{{.State.Running}}' "${name}")" == false ]]
[[ "$(docker inspect --format '{{.State.ExitCode}}' "${name}")" != 0 ]]

printf '%s\n' "smoke test passed for ${image}"
