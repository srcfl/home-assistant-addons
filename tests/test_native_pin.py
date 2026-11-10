"""Offline tests for scripts/native_pin.py (no network)."""
import http.client
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import native_pin  # noqa: E402

A = "a" * 64
B = "b" * 64
URL = "https://example.invalid/ftw-linux-arm64.tar.gz.sha256"


def fake_assets(tag, amd=A, arm=B, sha_arm=None):
    files = {
        "ftw-native-release.json": json.dumps(
            {"schema": 1, "channel": "beta", "tag": tag, "sha256": {"amd64": amd, "arm64": arm}}
        ).encode(),
        "ftw-linux-amd64.tar.gz.sha256": f"{amd}  ftw-linux-amd64.tar.gz\n".encode(),
        "ftw-linux-arm64.tar.gz.sha256": f"{sha_arm or arm}  ftw-linux-arm64.tar.gz\n".encode(),
    }
    return lambda t, name: files[name]


class ReceiptTest(unittest.TestCase):
    def test_validator_import_works_in_a_fresh_python_process(self):
        result = subprocess.run(
            [sys.executable, "-c", "from scripts import validate; validate.validate_repository()"],
            cwd=native_pin.ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_matching_sums(self):
        with mock.patch.object(native_pin, "asset", fake_assets("v0.160.0-beta.1")):
            self.assertEqual(native_pin.receipt("v0.160.0-beta.1"), {"amd64": A, "arm64": B})

    def test_rejects_sha_file_mismatch(self):
        with mock.patch.object(native_pin, "asset", fake_assets("v0.160.0-beta.1", sha_arm="c" * 64)):
            with self.assertRaisesRegex(SystemExit, "disagrees"):
                native_pin.receipt("v0.160.0-beta.1")

    def test_rejects_wrong_tag(self):
        with mock.patch.object(native_pin, "asset", fake_assets("v0.160.0-beta.2")):
            with self.assertRaisesRegex(SystemExit, "does not describe"):
                native_pin.receipt("v0.160.0-beta.1")

    def test_old_line_and_stable_tags_are_refused(self):
        for tag in ("v0.130.0-beta.1", "v3.8.0-beta.1", "v0.160.0", "latest"):
            with self.subTest(tag=tag), self.assertRaisesRegex(SystemExit, "not a new-line"):
                native_pin.receipt(tag)


def answer(body=b"ok"):
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = body
    return resp


def http_error(code, reason):
    return urllib.error.HTTPError(URL, code, reason, None, None)


class FetchTest(unittest.TestCase):
    """fetch() against a scripted urlopen: no network, no real pauses."""

    def setUp(self):
        self.urlopen = self.patch(native_pin.urllib.request, "urlopen")
        self.sleep = self.patch(native_pin.time, "sleep")
        self.stderr = self.patch(native_pin.sys, "stderr", new_callable=io.StringIO)

    def patch(self, *args, **kwargs):
        patcher = mock.patch.object(*args, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_succeeds_on_the_second_attempt_after_a_timeout(self):
        self.urlopen.side_effect = [TimeoutError("The read operation timed out"), answer(b"sums")]
        self.assertEqual(native_pin.fetch(URL), b"sums")
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(native_pin.PAUSE_S)
        self.assertIn(URL, self.stderr.getvalue())
        self.assertIn("timed out", self.stderr.getvalue())

    def test_succeeds_after_a_504(self):
        self.urlopen.side_effect = [http_error(504, "Gateway Time-out"), answer(b"sums")]
        self.assertEqual(native_pin.fetch(URL), b"sums")
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(native_pin.PAUSE_S)

    def test_succeeds_after_a_broken_connection(self):
        cut_short = answer()
        cut_short.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b"")
        for failure in (urllib.error.URLError(ConnectionRefusedError()), ConnectionResetError(), cut_short):
            with self.subTest(failure=failure):
                self.urlopen.reset_mock()
                self.urlopen.side_effect = [failure, answer(b"sums")]
                self.assertEqual(native_pin.fetch(URL), b"sums")
                self.assertEqual(self.urlopen.call_count, 2)

    def test_gives_up_after_the_last_attempt(self):
        for failure in (TimeoutError("The read operation timed out"), http_error(503, "Service Unavailable")):
            with self.subTest(failure=failure):
                self.urlopen.reset_mock()
                self.sleep.reset_mock()
                self.urlopen.side_effect = failure
                with self.assertRaises(type(failure)) as raised:
                    native_pin.fetch(URL)
                self.assertIs(raised.exception, failure)
                self.assertEqual(self.urlopen.call_count, native_pin.ATTEMPTS)
                self.assertEqual(self.sleep.call_count, native_pin.ATTEMPTS - 1)

    def test_a_404_fails_at_once(self):
        self.urlopen.side_effect = http_error(404, "Not Found")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            native_pin.fetch(URL)
        self.assertEqual(raised.exception.code, 404)
        self.assertEqual(self.urlopen.call_count, 1)
        self.sleep.assert_not_called()


class PinFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = pathlib.Path(self.tmp.name) / "ftw-0x-beta"
        shutil.copytree(native_pin.APP, self.app)
        patcher = mock.patch.object(native_pin, "APP", self.app)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_bump_rewrites_both_files(self):
        with mock.patch.object(native_pin, "asset", fake_assets("v0.160.0-beta.1")):
            native_pin.main(["x", "bump", "v0.160.0-beta.1"])
            self.assertEqual(
                native_pin.read_pin(), ("v0.160.0-beta.1", "0.160.0-beta.1", {"amd64": A, "arm64": B})
            )
            native_pin.main(["x", "check"])

    def test_image_key_is_refused(self):
        cfg = self.app / "config.yaml"
        cfg.write_text(cfg.read_text() + "image: ghcr.io/x/y\n")
        with self.assertRaisesRegex(SystemExit, "no image"):
            native_pin.read_pin()

    def test_delayed_release_event_cannot_downgrade_pin(self):
        before = {p.name: p.read_bytes() for p in self.app.iterdir() if p.is_file()}
        with mock.patch.object(native_pin, "asset") as download:
            native_pin.main(["x", "bump", "v0.131.0-beta.1"])
        download.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.app.iterdir() if p.is_file()})

    def test_bump_adds_release_notes_once(self):
        tag = "v0.160.0-beta.1"
        with mock.patch.object(native_pin, "asset", fake_assets(tag)):
            native_pin.main(["x", "bump", tag])
            native_pin.main(["x", "bump", tag])
        notes = (self.app / "CHANGELOG.md").read_text()
        self.assertEqual(notes.count("## 0.160.0-beta.1\n"), 1)
        self.assertIn(f"https://github.com/srcfl/ftw/releases/tag/{tag}", notes)


if __name__ == "__main__":
    unittest.main()
