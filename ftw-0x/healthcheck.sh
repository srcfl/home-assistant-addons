#!/usr/bin/env bash
# Healthy when Core answers /api/health. A new install serves only the setup
# wizard, where /api/health is 404; count that as healthy too.
# Loopback health checks cannot open /setup or any other UI route.
# Same rule as deploy/balena in srcfl/ftw. 0.x has no /api/status.
set -Eeuo pipefail

readonly base=http://127.0.0.1:18099
readonly agent='User-Agent: ftw-home-assistant-healthcheck'

if wget -q -T 4 -O /dev/null --header="${agent}" "${base}/api/health"; then
  exit 0
fi
code="$(wget -S -q -T 4 -O /dev/null --header="${agent}" "${base}/api/health" 2>&1 | awk '/^  HTTP\//{c=$2} END{print c}')" || true
[[ "${code}" == 404 ]] && exit 0
exit 1
