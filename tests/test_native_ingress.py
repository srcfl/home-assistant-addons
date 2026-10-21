"""Run the installed ingress health check against HTTP outcomes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import native_pin

ROOT = Path(__file__).resolve().parent.parent


class IngressHealthTest(unittest.TestCase):
    def test_only_the_health_route_is_needed_even_during_setup(self):
        for code, expected in ((200, 0), (404, 0), (500, 1), (0, 1)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                wget = work / "wget"
                wget.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
printf '  HTTP/1.1 %s Result\\n' "$CODE" >&2
[ "$CODE" = 200 ]
''')
                wget.chmod(0o755)
                env = dict(os.environ, PATH=f"{work}:{os.environ['PATH']}", CODE=str(code), CALLS=str(work / "calls"))
                result = subprocess.run(["bash", str(ROOT / "ftw-0x-beta/healthcheck.sh")],env=env,capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                calls = (work / "calls").read_text()
                self.assertIn("127.0.0.1:18099/api/health",calls)
                self.assertNotIn("/setup",calls)

    def test_same_tag_preserves_app_revision_and_next_beta_replaces_it(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            for filename in ("config.yaml", "Dockerfile", "CHANGELOG.md"):
                (app / filename).write_bytes((native_pin.APP / filename).read_bytes())
            with patch.object(native_pin,"APP",app):
                tag, version, sums = native_pin.read_pin()
                native_pin.write_pin(tag,sums)
                self.assertEqual(native_pin.read_pin()[1],version)
                native_pin.write_pin("v0.160.0-beta.1",sums)
                self.assertEqual(native_pin.read_pin()[1],"0.160.0-beta.1")


if __name__ == '__main__':
    unittest.main()
