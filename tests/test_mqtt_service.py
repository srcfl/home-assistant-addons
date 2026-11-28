"""Run the app's MQTT broker lookup against scripted Supervisor answers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("FTW_HA_MQTT_HOST", "FTW_HA_MQTT_PORT", "FTW_HA_MQTT_USERNAME", "FTW_HA_MQTT_PASSWORD")
MOSQUITTO = {"result": "ok", "data": {
    "host": "core-mosquitto", "port": 1883, "ssl": False, "protocol": "3.1.1",
    "username": "addons", "password": "a b'c\"$d", "addon": "core_mosquitto"}}
# Print what Core would receive, exactly, after run.sh's strict mode.
PROBE = """set -Eeuo pipefail
source "$1"
export_home_assistant_mqtt
for name in %s; do
  if declare -p "${name}" >/dev/null 2>&1; then printf '%%s=%%s\\0' "${name}" "${!name}"; fi
done
""" % " ".join(NAMES)


@unittest.skipIf(shutil.which("jq") is None, "the app image ships jq; this host has none")
class MQTTServiceTest(unittest.TestCase):
    def run_lookup(self, reply=None, *, token="supervisor-token", curl_fails=False, **extra):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            curl = work / "curl"
            curl.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CALLS"\n'
                            '[ -z "$FAIL" ] || exit 7\nprintf "%s" "$REPLY"\n')
            curl.chmod(0o755)
            env = dict(os.environ, PATH=f"{work}:{os.environ['PATH']}", CALLS=str(work / "calls"),
                       REPLY=json.dumps(reply) if isinstance(reply, dict) else (reply or ""),
                       FAIL="1" if curl_fails else "", **extra)
            env.pop("SUPERVISOR_TOKEN", None)
            if token:
                env["SUPERVISOR_TOKEN"] = token
            result = subprocess.run(["bash", "-c", PROBE, "probe", str(ROOT / "ftw-0x-beta/mqtt-service.sh")],
                                    env=env, capture_output=True, text=True)
            calls = (work / "calls").read_text().splitlines() if (work / "calls").exists() else []
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(item.split("=", 1) for item in result.stdout.split("\0") if item)
        return values, calls, result.stderr

    def test_passes_mosquitto_to_core(self):
        values, calls, log = self.run_lookup(MOSQUITTO)
        self.assertEqual(values, {"FTW_HA_MQTT_HOST": "core-mosquitto", "FTW_HA_MQTT_PORT": "1883",
                                  "FTW_HA_MQTT_USERNAME": "addons", "FTW_HA_MQTT_PASSWORD": "a b'c\"$d"})
        self.assertIn("Authorization: Bearer supervisor-token", calls)
        self.assertIn("http://supervisor/services/mqtt", calls)
        self.assertIn("core-mosquitto:1883", log)
        self.assertNotIn("a b'c", log)

    def test_core_still_starts_without_a_broker(self):
        no_broker = {"result": "error", "message": "Service not enabled", "data": {}}
        for name, kwargs in (("Supervisor refuses", {"curl_fails": True}),
                             ("no broker", {"reply": no_broker}),
                             ("not JSON", {"reply": "<html>"}),
                             ("TLS only", {"reply": {"data": dict(MOSQUITTO["data"], ssl=True, port=8883)}}),
                             ("bad port", {"reply": {"data": dict(MOSQUITTO["data"], port="1883")}})):
            with self.subTest(name):
                values, _, log = self.run_lookup(**kwargs)
                self.assertEqual(values, {})
                self.assertTrue(log.startswith("FTW: "), log)

    def test_only_supervisor_names_the_broker(self):
        stale = {name: "injected" for name in NAMES}
        values, calls, _ = self.run_lookup(MOSQUITTO, token="", **stale)
        self.assertEqual((values, calls), ({}, []))
        values, _, _ = self.run_lookup(curl_fails=True, **stale)
        self.assertEqual(values, {})

    def test_port_defaults_to_1883(self):
        data = {k: v for k, v in MOSQUITTO["data"].items() if k != "port"}
        values, _, _ = self.run_lookup({"result": "ok", "data": data})
        self.assertEqual(values["FTW_HA_MQTT_PORT"], "1883")


if __name__ == "__main__":
    unittest.main()
