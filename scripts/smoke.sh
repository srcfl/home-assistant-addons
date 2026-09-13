#!/usr/bin/env bash
set -Eeuo pipefail

image=${1:?usage: smoke.sh IMAGE}
name="ftw-ha-smoke-${RANDOM}"
volume="ftw-ha-data-${RANDOM}"
expected_core_version="$(docker image inspect --format '{{ index .Config.Labels "com.sourceful.ftw.core.version" }}' "${image}")"
[[ -n "${expected_core_version}" && "${expected_core_version}" != "<no value>" ]]

cleanup() {
  docker rm -f "${name}" >/dev/null 2>&1 || true
  docker volume rm "${volume}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Supervisor runs the app with Docker's default init because config.yaml leaves
# `init` alone, so Core is the child of docker-init rather than PID 1.
start() {
  docker run -d --init --name "${name}" --volume "${volume}:/data" "${image}" >/dev/null
}

wait_healthy() {
  for _ in {1..60}; do
    if [[ "$(docker inspect --format '{{.State.Health.Status}}' "${name}")" == healthy ]]; then
      return 0
    fi
    sleep 1
  done
  docker logs "${name}" >&2
  return 1
}

core_pid() {
  docker exec "${name}" bash -ceu '
    for status in /proc/[0-9]*/status; do
      if grep -q "^Name:	ftw$" "${status}" 2>/dev/null; then
        basename "$(dirname "${status}")"
        exit 0
      fi
    done
    exit 1'
}

docker volume create "${volume}" >/dev/null
start
wait_healthy

docker exec "${name}" bash -ceu 'test "$FTW_SELFUPDATE_ENABLED" = 0; test "$FTW_BUNDLE" = home_assistant_addon'
docker exec "${name}" bash -ceu 'test "$FTW_IMAGE_TAG" = "$1"' -- "${expected_core_version}"
docker exec "${name}" /usr/local/bin/healthcheck.sh

# Core runs unprivileged even though the wrapper started as root.
pid="$(core_pid)"
docker exec "${name}" bash -ceu 'test "$(stat -c %u "/proc/$1")" = 100' -- "${pid}"

docker exec "${name}" bash -ceu 'install -d -o 100 -g 101 /data/drivers; printf "%s\n" "-- user marker" >/data/drivers/custom.lua; : >/data/config.yaml; chown 100:101 /data/config.yaml /data/drivers/custom.lua'
docker exec "${name}" /usr/local/bin/healthcheck.sh

docker stop --time 20 "${name}" >/dev/null
[[ "$(docker inspect --format '{{.State.ExitCode}}' "${name}")" == 0 ]]
docker rm "${name}" >/dev/null

start
wait_healthy
docker exec "${name}" /usr/local/bin/healthcheck.sh
docker exec "${name}" grep -Fx -- '-- user marker' /data/drivers/custom.lua
if docker exec "${name}" bash -ceu \
  'for process in /proc/[0-9]*/cmdline; do tr "\0" " " <"${process}"; printf "\n"; done' \
  | grep -q ftw-updater; then
  printf '%s\n' "unexpected FTW updater process" >&2
  exit 1
fi

# Core dying must end the container so Supervisor restarts it.
pid="$(core_pid)"
docker exec "${name}" kill -KILL "${pid}"
for _ in {1..30}; do
  if [[ "$(docker inspect --format '{{.State.Running}}' "${name}")" == false ]]; then
    break
  fi
  sleep 1
done
[[ "$(docker inspect --format '{{.State.Running}}' "${name}")" == false ]]
[[ "$(docker inspect --format '{{.State.ExitCode}}' "${name}")" != 0 ]]

printf '%s\n' "smoke test passed for ${image}"
