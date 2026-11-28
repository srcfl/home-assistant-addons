# shellcheck shell=bash
# Sourced by run.sh. Asks Supervisor for Home Assistant's MQTT broker
# (`services: mqtt:want`) and hands it to Core in FTW_HA_MQTT_*, so FTW's
# entities appear in Home Assistant without anyone typing a broker or a
# password. Core uses it only while its own broker setting is empty.
# A missing broker never keeps Core from starting.

export_home_assistant_mqtt() {
  local reply host port ssl
  # Only Supervisor's answer may name the broker.
  unset FTW_HA_MQTT_HOST FTW_HA_MQTT_PORT FTW_HA_MQTT_USERNAME FTW_HA_MQTT_PASSWORD
  [[ -n "${SUPERVISOR_TOKEN:-}" ]] || return 0
  if ! reply="$(curl -fsS -m 10 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
      http://supervisor/services/mqtt 2>/dev/null)" ||
    ! host="$(jq -er '.data.host | strings | select(length > 0)' <<<"${reply}" 2>/dev/null)"; then
    printf 'FTW: Home Assistant has no MQTT broker. Add the Mosquitto broker app, then restart FTW, to see FTW in Home Assistant.\n' >&2
    return 0
  fi
  if ! port="$(jq -er '.data.port // 1883 | numbers | select(. == floor and . > 0 and . < 65536)' <<<"${reply}" 2>/dev/null)"; then
    printf "FTW: ignoring Home Assistant's MQTT broker: bad port\n" >&2
    return 0
  fi
  ssl="$(jq -r '.data.ssl // false' <<<"${reply}")" || ssl=false
  if [[ "${ssl}" == true ]]; then
    printf "FTW: Home Assistant's MQTT broker needs TLS, which FTW does not speak yet; set a broker in FTW's settings\n" >&2
    return 0
  fi
  FTW_HA_MQTT_HOST="${host}"
  FTW_HA_MQTT_PORT="${port}"
  FTW_HA_MQTT_USERNAME="$(jq -r '.data.username // "" | strings' <<<"${reply}")" || FTW_HA_MQTT_USERNAME=
  FTW_HA_MQTT_PASSWORD="$(jq -r '.data.password // "" | strings' <<<"${reply}")" || FTW_HA_MQTT_PASSWORD=
  export FTW_HA_MQTT_HOST FTW_HA_MQTT_PORT FTW_HA_MQTT_USERNAME FTW_HA_MQTT_PASSWORD
  printf "FTW: Home Assistant's MQTT broker is %s:%s\n" "${host}" "${port}" >&2
}
