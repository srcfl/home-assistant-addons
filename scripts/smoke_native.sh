#!/usr/bin/env bash
# Smoke for ftw-0x-beta under Supervisor-like conditions, against the real
# FTW 0.x package (scripts/smoke.sh targets the 3.x fixture, whose empty
# config real 0.x Core rejects).
#   host network, /data volume with options.json, Docker init, uid 100:101,
#   setup wizard healthy, valid config -> /api/health, restart persistence,
#   cold backup (stop, tar /data, restore into a fresh volume), Core death
#   ends the container.
set -Eeuo pipefail
image=${1:?usage: smoke_native.sh IMAGE}
port=${FTW_SMOKE_PORT:-8080}
name="ftw0x-smoke-${RANDOM}"; vol="ftw0x-data-${RANDOM}"; vol2="${vol}-restored"
tmp="$(mktemp -d)"
log() { printf 'smoke-native: %s\n' "$*"; }
fail() { printf 'smoke-native: FAIL %s\n' "$*" >&2; exit 1; }
cleanup() {
  local s=$?
  if [[ $s -ne 0 ]]; then docker logs "${name}" 2>&1 | tail -20 >&2 || true; fi
  docker rm -f "${name}" >/dev/null 2>&1 || true
  docker volume rm "${vol}" "${vol2}" >/dev/null 2>&1 || true
  rm -rf "${tmp}"
}
trap cleanup EXIT

# Ownership repair must stop before touching a linked file or nested mount.
docker run --rm --network none --entrypoint bash "${image}" -ceu '
  mkdir -p /data /outside
  touch /outside/marker
  ln -s /outside /data/drivers
  if /usr/local/bin/run.sh 2>/tmp/error; then exit 1; fi
  grep -q "/data/drivers must not be a link" /tmp/error
  test "$(stat -c %u:%g /outside/marker)" = 0:0
'
docker run --rm --network none --entrypoint bash "${image}" -ceu '
  mkdir -p /data
  touch /data/state.db
  ln /data/state.db /data/linked
  if /usr/local/bin/run.sh 2>/tmp/error; then exit 1; fi
  grep -q "/data contains a hard link" /tmp/error
  test "$(stat -c %u:%g /data/linked)" = 0:0
'
docker run --rm --network none --mount type=tmpfs,destination=/data/nested \
  --entrypoint bash "${image}" -ceu '
  touch /data/state.db
  if /usr/local/bin/run.sh 2>/tmp/error; then exit 1; fi
  grep -q "/data contains a nested mount" /tmp/error
  test "$(stat -c %u:%g /data/state.db)" = 0:0
'
log "restore repair refuses links and nested mounts"

run() {
  local -a docker_args
  read -r -a docker_args <<< "${FTW_SMOKE_DOCKER_ARGS:-}"
  docker run -d --init "${docker_args[@]}" --network host --name "${name}" -v "$1:/data" "${image}" >/dev/null
}
healthy() {
  for _ in $(seq 1 90); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' "${name}" 2>/dev/null)" == healthy ]] && return 0
    [[ "$(docker inspect -f '{{.State.Running}}' "${name}")" == true ]] || fail "container exited"
    sleep 1
  done
  fail "not healthy in 90s"
}
http() { curl -fsSL -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}$1"; }

docker volume create "${vol}" >/dev/null
# Supervisor writes options.json into /data as root before start.
docker run --rm -v "${vol}:/data" --entrypoint sh "${image}" -c 'echo "{}" >/data/options.json'
run "${vol}"; healthy
log "fresh install healthy (setup wizard); /setup -> $(http /setup)"
docker exec "${name}" bash -ceu 'test "$FTW_SELFUPDATE_ENABLED" = 0; test "$FTW_BUNDLE" = home_assistant_addon'
owner="$(docker exec "${name}" sh -c 'for p in /proc/[0-9]*; do [ "$p" = "/proc/$$" ] && continue; tr "\\0" " " <$p/cmdline 2>/dev/null | grep -q -- "/app/ftw -config" && stat -c %u:%g $p; done' | awk 'NR==1')"
[[ "${owner}" == 100:101 ]] || fail "Core runs as ${owner}, want 100:101"
log "Core runs as ${owner}"
[[ "$(http /)" == 200 ]] || fail "web UI root"
log "web UI / -> 200"
# The sidebar panel answers only Supervisor's ingress proxy (172.30.32.2).
panel="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:8093/")" || true
[[ "${panel}" == 403 ]] || fail "sidebar panel from 127.0.0.1 -> ${panel}, want 403"
panel_owner="$(docker exec "${name}" sh -c 'for p in /proc/[0-9]*; do [ "$p" = "/proc/$$" ] && continue; tr "\\0" " " <$p/cmdline 2>/dev/null | grep -q -- "httpd -p 8093" && stat -c %u:%g $p; done; true' | awk 'NR==1')"
[[ "${panel_owner}" == 100:101 ]] || fail "sidebar panel runs as ${panel_owner:-nothing}, want 100:101"
log "sidebar panel refuses non-Supervisor clients"

docker exec -u 100:101 "${name}" sh -c 'cat >/data/config.yaml <<Y
site:
  name: "HA smoke"
fuse:
  max_amps: 16
  phases: 3
  voltage: 230
drivers: []
api:
  port: 8080
Y
mkdir -p /data/drivers && echo "-- user marker" >/data/drivers/custom.lua'
docker restart -t 30 "${name}" >/dev/null; healthy
[[ "$(http /api/health)" == 200 ]] || fail "/api/health after config"
log "configured Core: /api/health -> 200"
# Exercise the shipped worker as the same unprivileged user as Core.
worker=$(docker exec -u 100:101 "${name}" sh -c 'printf '\''{"type":"handshake"}\n'\'' | /app/optimizer/native/bundle/ftw-solver-linux-$(dpkg --print-architecture)')
[[ "${worker}" == *'"protocol_version":1'* ]] || fail "Energyplan handshake: ${worker}"
log "bundled Energyplan worker answered its handshake"
# Core must restart itself in this bundle even without Supervisor's watchdog.
curl -fsS -m 5 -X POST "http://127.0.0.1:${port}/api/restart" >/dev/null
sleep 2
healthy
[[ "$(http /api/health)" == 200 ]] || fail "/api/health after FTW restart"
log "FTW's own restart returned to healthy"
stats() { log "usage ($1): $(docker stats --no-stream --format '{{.CPUPerc}} cpu, {{.MemUsage}}' "${name}"), /data $(docker exec "${name}" du -sh /data | cut -f1)"; }
stats "configured, just started"
sleep "${FTW_SMOKE_SOAK_S:-0}"
stats "after ${FTW_SMOKE_SOAK_S:-0}s"
docker exec "${name}" test -f /data/state.db || log "note: no state.db yet"
docker exec "${name}" ls /data

log "cold backup: stop, tar /data, restore into a fresh volume"
docker stop -t 60 "${name}" >/dev/null
[[ "$(docker inspect -f '{{.State.ExitCode}}' "${name}")" == 0 ]] || fail "clean stop exit code"
t0=$(date +%s.%N)
docker run --rm -v "${vol}:/data:ro" -v "${tmp}:/b" --entrypoint tar "${image}" -C /data -czpf /b/backup.tgz .
log "cold backup: $(du -h "${tmp}/backup.tgz" | cut -f1) in $(echo "$(date +%s.%N) - ${t0}" | bc | cut -c1-5)s (tar+gzip, Supervisor's own format differs)"
docker rm "${name}" >/dev/null
docker volume create "${vol2}" >/dev/null
docker run --rm -v "${vol2}:/data" -v "${tmp}:/b" --entrypoint tar "${image}" -C /data -xzpf /b/backup.tgz
# Match a real Supervisor/securetar restore, rather than tar's preserved uid.
docker run --rm -v "${vol2}:/data" --entrypoint sh "${image}" -ec \
  'find -P /data -xdev -exec chown --no-dereference 0:0 {} +; find -P /data -xdev -type f -exec chmod 0644 {} +'
run "${vol2}"; healthy
[[ "$(http /api/health)" == 200 ]] || fail "/api/health after restore"
docker exec "${name}" grep -Fxq -- '-- user marker' /data/drivers/custom.lua || fail "user driver lost"
docker exec "${name}" grep -q 'HA smoke' /data/config.yaml || fail "config lost"
docker exec "${name}" sh -ec 'test "$(stat -c %u:%g /data/state.db)" = 100:101; test "$(stat -c %a /data/config.yaml)" = 600'
log "restored: config, user driver and health intact"

pid="$(docker exec "${name}" sh -c 'for p in /proc/[0-9]*; do [ "$p" = "/proc/$$" ] && continue; tr "\\0" " " <$p/cmdline 2>/dev/null | grep -q -- "/app/ftw -config" && basename $p; done' | awk 'NR==1')"
docker exec "${name}" sh -c "kill -KILL ${pid}"
for _ in $(seq 1 30); do [[ "$(docker inspect -f '{{.State.Running}}' "${name}")" == false ]] && break; sleep 1; done
[[ "$(docker inspect -f '{{.State.Running}}' "${name}")" == false ]] || fail "kept running after Core died"
log "Core death ends the container (exit $(docker inspect -f '{{.State.ExitCode}}' "${name}"))"
log "PASS ${image}"
