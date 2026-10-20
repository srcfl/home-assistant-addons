"""Offline tests for scripts/native_pin.py (no network)."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import native_pin  # noqa: E402

A = "a" * 64
B = "b" * 64


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
