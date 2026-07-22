#!/usr/bin/env bash
set -Eeuo pipefail

readonly runtime_uid=100
readonly runtime_gid=101
readonly optimizer_socket=/run/ftw-optimizer/optimizer.sock
readonly optimizer_pid_file=/run/ftw-optimizer/worker.pid
readonly core_pid_file=/run/ftw/core.pid

core_pid=""
optimizer_monitor_pid=""
stop_requested=0

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

prepare_paths() {
  install -d -o "${runtime_uid}" -g "${runtime_gid}" -m 0750 \
    /data /data/drivers /data/driver-repository /run/ftw /run/ftw-optimizer
  rm -f "${optimizer_socket}" "${optimizer_pid_file}" "${core_pid_file}"
}

monitor_optimizer() (
  set -Eeuo pipefail

  child_pid=""
  monitor_stopping=0
  delay=1
  failures=0
  last_log=0

  # shellcheck disable=SC2329 # Called by the signal trap.
  stop_monitor() {
    monitor_stopping=1
    if [[ -n "${child_pid}" ]]; then
      kill -TERM "${child_pid}" 2>/dev/null || true
    fi
  }
  trap stop_monitor TERM INT

  while (( monitor_stopping == 0 )); do
    rm -f "${optimizer_socket}"
    started_at="$(date +%s)"
    setpriv --reuid="${runtime_uid}" --regid="${runtime_gid}" --clear-groups -- \
      /opt/venv/bin/ftw-optimizer &
    child_pid=$!
    printf '%s\n' "${child_pid}" >"${optimizer_pid_file}"

    set +e
    wait "${child_pid}"
    status=$?
    set -e
    child_pid=""
    rm -f "${optimizer_pid_file}" "${optimizer_socket}"

    if (( monitor_stopping != 0 )); then
      exit 0
    fi

    now="$(date +%s)"
    runtime=$((now - started_at))
    if (( runtime >= 300 )); then
      delay=1
      failures=0
    fi
    failures=$((failures + 1))

    if (( failures <= 5 || now - last_log >= 300 )); then
      log "Optimizer exited with status ${status}; Core keeps its Go fallback. Retrying in ${delay}s."
      last_log="${now}"
    fi

    sleep "${delay}" &
    child_pid=$!
    set +e
    wait "${child_pid}"
    set -e
    child_pid=""
    if (( delay < 60 )); then
      delay=$((delay * 2))
      if (( delay > 60 )); then
        delay=60
      fi
    fi
  done
)

# shellcheck disable=SC2329 # Called by the signal trap.
request_stop() {
  stop_requested=1
  [[ -n "${core_pid}" ]] && kill -TERM "${core_pid}" 2>/dev/null || true
  [[ -n "${optimizer_monitor_pid}" ]] \
    && kill -TERM "${optimizer_monitor_pid}" 2>/dev/null || true
}

wait_for_exit() {
  local pid=$1
  local seconds=$2
  local count
  for ((count = 0; count < seconds; count += 1)); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      wait "${pid}" 2>/dev/null || true
      return 0
    fi
    sleep 1
  done
  return 1
}

prepare_paths

# These values also exist in config.yaml and the image. Export them here so a
# future injected environment cannot turn self-update or process transport on.
export FTW_SELFUPDATE_ENABLED=0
export FTW_OPTIMIZER_TRANSPORT=unix
export FTW_OPTIMIZER_SOCKET="${optimizer_socket}"

trap request_stop TERM INT

monitor_optimizer &
optimizer_monitor_pid=$!

setpriv --reuid="${runtime_uid}" --regid="${runtime_gid}" --clear-groups -- \
  /app/ftw \
  -config /data/config.yaml \
  -web /app/web \
  -drivers /app/drivers \
  -user-drivers /data/drivers &
core_pid=$!
printf '%s\n' "${core_pid}" >"${core_pid_file}"

set +e
wait "${core_pid}"
core_status=$?
while kill -0 "${core_pid}" 2>/dev/null; do
  wait "${core_pid}"
  core_status=$?
done
set -e
rm -f "${core_pid_file}"

kill -TERM "${optimizer_monitor_pid}" 2>/dev/null || true
if ! wait_for_exit "${optimizer_monitor_pid}" 30; then
  log "Optimizer monitor did not stop in 30s; sending SIGKILL."
  kill -KILL "${optimizer_monitor_pid}" 2>/dev/null || true
  wait "${optimizer_monitor_pid}" 2>/dev/null || true
fi

if (( stop_requested != 0 )); then
  exit 0
fi
exit "${core_status}"
