"""Run the whole suite again as the next pin PR will run it.

A bot opens the pin PRs and nobody watches them. A test that only holds for
today's pin passes in the PR that adds it and fails later, on a pin PR, where
it blocks every release until someone looks. A fixed "next" version did that
to four betas in November 2026 (#43); a seeded version did it in September
(#10).

So this copies the checkout, moves the copy's pin with the real bump code and
runs every test there. A test that depends on the pinned version then fails
here, in the PR that adds it.
"""
import contextlib
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import native_pin

ROOT = pathlib.Path(__file__).resolve().parents[1]
INSIDE = "FTW_PIN_REHEARSAL"
# Far enough ahead that no version written into a test as "the next one" is
# still ahead of it.
MINORS_AHEAD = 1000


@unittest.skipIf(os.environ.get(INSIDE), "this run is the rehearsal")
class PinRehearsalTest(unittest.TestCase):
    def test_suite_passes_on_a_later_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = pathlib.Path(directory)
            # Tracked files plus new ones not yet added, so a test file that
            # is still untracked is rehearsed too.
            listed = subprocess.check_output(
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                cwd=ROOT, text=True)
            for name in filter(None, listed.split("\0")):
                if (ROOT / name).is_file():
                    (copy / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / name, copy / name)

            minor = native_pin.tag_order(native_pin.read_pin()[0])[0]
            later = f"v0.{minor + MINORS_AHEAD}.0-beta.1"
            sums = {"amd64": "a" * 64, "arm64": "b" * 64}
            with mock.patch.object(native_pin, "APP", copy / "ftw-0x-beta"), \
                    mock.patch.object(native_pin, "receipt", return_value=sums), \
                    contextlib.redirect_stdout(io.StringIO()):
                native_pin.main(["native_pin.py", "bump", later])

            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                cwd=copy, env=dict(os.environ, **{INSIDE: "1"}), capture_output=True, text=True)
            self.assertEqual(
                result.returncode, 0,
                f"these tests fail once the pin moves (rehearsed with {later}); "
                f"take versions from the pin instead of writing them down:\n{result.stderr[-6000:]}")


if __name__ == "__main__":
    unittest.main()
