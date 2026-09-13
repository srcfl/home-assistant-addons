#!/usr/bin/env bash
# Setup page until Core has a configuration, then Core's status endpoint. Uses
# the wget the Core image ships for its own health check; the image has no
# Python.
set -Eeuo pipefail

readonly base=http://127.0.0.1:8080
readonly agent='User-Agent: ftw-home-assistant-healthcheck'

if [[ ! -f /data/config.yaml ]]; then
  exec wget -q -T 4 -O /dev/null --header="${agent}" "${base}/setup"
fi

body="$(wget -q -T 4 -O - --header="${agent}" "${base}/api/status")"
[[ "${body}" == \{* ]]
