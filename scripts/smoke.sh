#!/usr/bin/env bash
set -Eeuo pipefail

image=${1:?usage: smoke.sh IMAGE}
name="ftw-ha-smoke-${RANDOM}"
volume="ftw-ha-data-${RANDOM}"

log() {
  printf 'smoke: %s\n' "$*"
}

fail() {
  printf 'smoke: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local status=$?
  if [[ ${status} -ne 0 ]]; then
    printf 'smoke: failed with exit %s; container state and logs follow\n' "${status}" >&2
    docker inspect --format '{{json .State}}' "${name}" >&2 2>/dev/null || true
    docker logs "${name}" >&2 2>&1 || true
  fi
  docker rm -f "${name}" >/dev/null 2>&1 || true
  docker volume rm "${volume}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

expected_core_version="$(docker image inspect --format '{{ index .Config.Labels "com.sourceful.ftw.core.version" }}' "${image}")"
if [[ -z "${expected_core_version}" || "${expected_core_version}" == "<no value>" ]]; then
  fail "image ${image} lacks the com.sourceful.ftw.core.version label"
fi
log "image ${image} pins Core ${expected_core_version}"

# Supervisor runs the app with Docker's default init because config.yaml leaves
# `init` alone, so Core is the child of docker-init rather than PID 1.
start() {
  docker run -d --init --name "${name}" --volume "${volume}:/data" "${image}" >/dev/null
  log "started ${name}"
}

wait_healthy() {
  for _ in {1..60}; do
    if [[ "$(docker inspect --format '{{.State.Health.Status}}' "${name}")" == healthy ]]; then
      log "${name} is healthy"
      return 0
    fi
    sleep 1
  done
  fail "${name} did not become healthy in 60s"
}

# Find Core by an argument equal to /app/ftw. That holds for the real binary
# and for the fixture, whose shebang makes the process name python3 instead.
core_pid() {
  docker exec "${name}" bash -ceu '
    for cmdline in /proc/[0-9]*/cmdline; do
      pid="${cmdline#/proc/}"
      pid="${pid%/cmdline}"
      if [[ "${pid}" == "$$" ]]; then
        continue
      fi
      if tr "\0" "\n" <"${cmdline}" 2>/dev/null | grep -qx "/app/ftw"; then
        printf "%s\n" "${pid}"
        exit 0
      fi
    done
    exit 1'
}

docker volume create "${volume}" >/dev/null
start
wait_healthy

log "checking the bundle contract"
docker exec "${name}" bash -ceu 'test "$FTW_SELFUPDATE_ENABLED" = 0; test "$FTW_BUNDLE" = home_assistant_addon'
docker exec "${name}" bash -ceu 'test "$FTW_IMAGE_TAG" = "$1"' -- "${expected_core_version}"
docker exec "${name}" /usr/local/bin/healthcheck.sh

# Core runs unprivileged even though the wrapper started as root.
pid="$(core_pid)"
log "Core runs as pid ${pid}"
docker exec "${name}" bash -ceu 'test "$(stat -c %u "/proc/$1")" = 100' -- "${pid}"

log "writing config and a user driver"
docker exec "${name}" bash -ceu 'install -d -o 100 -g 101 /data/drivers; printf "%s\n" "-- user marker" >/data/drivers/custom.lua; : >/data/config.yaml; chown 100:101 /data/config.yaml /data/drivers/custom.lua'
docker exec "${name}" /usr/local/bin/healthcheck.sh

log "stopping and restarting with the same volume"
docker stop --time 20 "${name}" >/dev/null
[[ "$(docker inspect --format '{{.State.ExitCode}}' "${name}")" == 0 ]] || fail "clean stop exited non-zero"
docker rm "${name}" >/dev/null

start
wait_healthy
docker exec "${name}" /usr/local/bin/healthcheck.sh
docker exec "${name}" grep -Fx -- '-- user marker' /data/drivers/custom.lua
if docker exec "${name}" bash -ceu \
  'for process in /proc/[0-9]*/cmdline; do tr "\0" " " <"${process}"; printf "\n"; done' \
  | grep -q ftw-updater; then
  fail "unexpected FTW updater process"
fi

# Core dying must end the container so Supervisor restarts it.
pid="$(core_pid)"
log "killing Core pid ${pid}; the container must exit"
docker exec "${name}" bash -ceu 'kill -KILL "$1"' -- "${pid}"
for _ in {1..30}; do
  if [[ "$(docker inspect --format '{{.State.Running}}' "${name}")" == false ]]; then
    break
  fi
  sleep 1
done
[[ "$(docker inspect --format '{{.State.Running}}' "${name}")" == false ]] || fail "container kept running after Core died"
[[ "$(docker inspect --format '{{.State.ExitCode}}' "${name}")" != 0 ]] || fail "container exited 0 after Core was killed"

log "smoke test passed for ${image}"
