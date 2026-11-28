"""Offline tests for scripts/native_pin.py (no network)."""
import http.client
import io
import json
import pathlib
import re
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


def fake_assets(tag, amd=A, arm=B, sha_arm=None, channel=None):
    channel = channel or ("beta" if "-beta." in tag else "stable")
    files = {
        "ftw-native-release.json": json.dumps(
            {"schema": 1, "channel": channel, "tag": tag, "sha256": {"amd64": amd, "arm64": arm}}
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

    def test_old_line_tags_are_refused(self):
        for tag in ("v0.130.0-beta.1", "v3.8.0-beta.1", "v0.130.4", "v3.8.0", "v0.160.0-rc.1", "latest"):
            with self.subTest(tag=tag), self.assertRaisesRegex(SystemExit, "not a new-line"):
                native_pin.receipt(tag)

    def test_a_receipt_must_name_the_tag_channel(self):
        with mock.patch.object(native_pin, "asset", fake_assets("v0.160.0")):
            self.assertEqual(native_pin.receipt("v0.160.0"), {"amd64": A, "arm64": B})
        for tag, wrong in (("v0.160.0", "beta"), ("v0.160.0-beta.1", "stable")):
            with self.subTest(tag=tag), mock.patch.object(native_pin, "asset", fake_assets(tag, channel=wrong)):
                with self.assertRaisesRegex(SystemExit, "does not describe"):
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


def unlisted_copy(dest):
    """The stable app as it is before the first stable, whatever main pins now."""
    shutil.copytree(native_pin.STABLE_APP, dest)
    listed = dest / "config.yaml"
    if listed.exists():
        text = re.sub(r'(?m)^(version:|\s+FTW_BUNDLE_VERSION:|\s+FTW_IMAGE_TAG:).*$', r'\1 ""', listed.read_text())
        (dest / native_pin.UNLISTED).write_text(text)
        listed.unlink()
        build = dest / "Dockerfile"
        build.write_text(re.sub(r"(?m)^(ARG FTW_(?:VERSION|SHA256_AMD64|SHA256_ARM64)=).*$", r"\1", build.read_text()))
    return dest


class AppCopies(unittest.TestCase):
    """Both apps copied to a scratch folder; tests never touch the checkout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = pathlib.Path(self.tmp.name) / "ftw-0x-beta"
        shutil.copytree(native_pin.APP, self.app)
        self.stable = unlisted_copy(pathlib.Path(self.tmp.name) / "ftw-0x")
        for name, path in (("APP", self.app), ("STABLE_APP", self.stable)):
            patcher = mock.patch.object(native_pin, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        # One minor ahead of whatever the app pins today. A fixed "next" version
        # stops being next the day FTW releases it, and every pin PR then fails.
        minor = native_pin.tag_order(native_pin.read_pin()[0])[0]
        self.newer = f"v0.{minor + 1}.0-beta.1"


class PinFilesTest(AppCopies):
    def test_bump_rewrites_both_files(self):
        with mock.patch.object(native_pin, "asset", fake_assets(self.newer)):
            native_pin.main(["x", "bump", self.newer])
            self.assertEqual(
                native_pin.read_pin(), (self.newer, self.newer[1:], {"amd64": A, "arm64": B})
            )
            native_pin.main(["x", "check"])

    def without_image(self, config):
        config.write_text(re.sub(r"(?m)^image:.*\n", "", config.read_text()))

    def test_bump_names_the_prebuilt_image_once(self):
        cfg = self.app / "config.yaml"
        self.without_image(cfg)  # as the beta app is before its first pin with an image
        native_pin.read_pin()
        later = f"{self.newer[:-1]}2"
        for tag in (self.newer, later):
            with mock.patch.object(native_pin, "asset", fake_assets(tag)):
                native_pin.main(["x", "bump", tag])
            text = cfg.read_text()
            self.assertEqual(re.findall(r"(?m)^image:.*$", text), [native_pin.IMAGE_LINE])
            self.assertIn(f'version: "{tag[1:]}"\n{native_pin.IMAGE_LINE}\n', text)
            self.assertEqual(native_pin.image(text), native_pin.IMAGE)

    def test_only_the_prebuilt_image_is_accepted(self):
        cfg = self.app / "config.yaml"
        self.without_image(cfg)
        text = cfg.read_text()
        for extra in ("image: ghcr.io/x/y\n", 'image: "ghcr.io/srcfl/home-assistant-addons/ftw"\n',
                      f"{native_pin.IMAGE_LINE}\n{native_pin.IMAGE_LINE}\n"):
            cfg.write_text(text + extra)
            with self.subTest(extra=extra), self.assertRaisesRegex(SystemExit, "must pull"):
                native_pin.read_pin()
        cfg.write_text(text + f"{native_pin.IMAGE_LINE}\n")
        native_pin.read_pin()

    def test_delayed_release_event_cannot_downgrade_pin(self):
        before = {p.name: p.read_bytes() for p in self.app.iterdir() if p.is_file()}
        with mock.patch.object(native_pin, "asset") as download:
            native_pin.main(["x", "bump", "v0.131.0-beta.1"])
        download.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.app.iterdir() if p.is_file()})

    def test_bump_adds_release_notes_once(self):
        tag = self.newer
        with mock.patch.object(native_pin, "asset", fake_assets(tag)):
            native_pin.main(["x", "bump", tag])
            native_pin.main(["x", "bump", tag])
        notes = (self.app / "CHANGELOG.md").read_text()
        self.assertEqual(notes.count(f"## {tag[1:]}\n"), 1)
        self.assertIn(f"https://github.com/srcfl/ftw/releases/tag/{tag}", notes)

    def test_unreleased_app_changes_ship_with_the_next_pin(self):
        changelog = self.app / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## Unreleased\n\n- App change.\n\n## 0.131.0-beta.1\n\n- Old.\n")
        with mock.patch.object(native_pin, "asset", fake_assets(self.newer)):
            native_pin.main(["x", "bump", self.newer])
        self.assertEqual(changelog.read_text(), (
            f"# Changelog\n\n## {self.newer[1:]}\n\n"
            f"- Update FTW to [{self.newer}](https://github.com/srcfl/ftw/releases/tag/{self.newer}).\n"
            "- App change.\n\n## 0.131.0-beta.1\n\n- Old.\n"))


if __name__ == "__main__":
    unittest.main()


class StablePinTest(AppCopies):
    """The stable app takes only stable releases and is listed with the first.
    The beta app follows Core's beta channel: the highest release of either."""

    def setUp(self):
        super().setUp()
        self.minor = native_pin.tag_order(native_pin.read_pin()[0])[0]
        # Below the beta pin, as a stable that trails the newest beta is.
        self.first, self.second = f"v0.{self.minor - 1}.0", f"v0.{self.minor - 1}.1"
        self.above = f"v0.{self.minor + 1}.0"

    def files(self, directory):
        return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}

    def bump(self, tag):
        with mock.patch.object(native_pin, "asset", fake_assets(tag)):
            native_pin.main(["x", "bump", tag])

    def check(self):
        """Run `check` against fake receipts for whatever the apps pin."""
        asked = []

        def asset(tag, name):
            asked.append(tag)
            return fake_assets(tag)(tag, name)

        out = io.StringIO()
        with mock.patch.object(native_pin, "asset", asset), mock.patch.object(native_pin.sys, "stdout", out):
            native_pin.main(["x", "check"])
        return set(asked), out.getvalue()

    def test_release_order_across_channels(self):
        m = self.minor
        ordered = [f"v0.{m}.0-beta.1", f"v0.{m}.0-beta.2", f"v0.{m}.0", f"v0.{m}.1-beta.1", f"v0.{m}.1",
                   f"v0.{m + 1}.0-beta.1"]
        self.assertEqual(sorted(reversed(ordered), key=native_pin.tag_order), ordered)

    def test_newest_release_is_the_highest_of_either_channel(self):
        m = self.minor
        for tags, newest in (([f"v0.{m}.0-beta.3", f"v0.{m}.0", "v3.8.0", "drivers-stable"], f"v0.{m}.0"),
                             ([f"v0.{m}.0", f"v0.{m}.1-beta.1", "v0.130.4"], f"v0.{m}.1-beta.1")):
            releases = json.dumps([{"tag_name": tag} for tag in tags]).encode()
            with self.subTest(tags=tags), mock.patch.object(native_pin, "fetch", return_value=releases):
                self.assertEqual(native_pin.latest_tag(), newest)

    def test_unlisted_app_pins_nothing(self):
        self.assertEqual(native_pin.read_pin("stable"), (None, None, None))
        self.assertFalse((self.stable / "config.yaml").exists())
        beta = f"v0.{self.minor + 1}.0-beta.1"
        self.bump(beta)
        asked, said = self.check()
        self.assertEqual(asked, {beta})
        self.assertIn("ftw-0x is not listed", said)

    def test_first_stable_lists_the_app(self):
        beta = self.files(self.app)
        self.bump(self.first)
        self.assertEqual(native_pin.read_pin("stable"), (self.first, self.first[1:], {"amd64": A, "arm64": B}))
        self.assertFalse((self.stable / native_pin.UNLISTED).exists())
        config = (self.stable / "config.yaml").read_text()
        self.assertTrue(config.startswith("name: FTW\n"), config[:80])
        self.assertIn("\nslug: ftw-0x\n", config)
        notes = (self.stable / "CHANGELOG.md").read_text()
        self.assertTrue(notes.startswith(f"# Changelog\n\n## {self.first[1:]}\n\n- Update FTW to [{self.first}]"), notes)
        self.assertNotIn("## Unreleased", notes)
        self.assertEqual(beta, self.files(self.app), "a stable below the beta pin must not move the beta app")
        newer_beta = f"v0.{self.minor + 1}.0-beta.1"
        self.bump(newer_beta)
        asked, said = self.check()
        self.assertEqual(asked, {newer_beta, self.first})
        self.assertIn(f"ftw-0x pins {self.first}", said)

    def test_a_stable_above_every_beta_moves_both_apps(self):
        self.bump(self.above)
        for name in ("beta", "stable"):
            self.assertEqual(native_pin.read_pin(name), (self.above, self.above[1:], {"amd64": A, "arm64": B}))
            notes = (native_pin.app_dir(name) / "CHANGELOG.md").read_text()
            self.assertTrue(notes.startswith(f"# Changelog\n\n## {self.above[1:]}\n\n"), notes[:80])
        # A beta of that same version is older; the next one moves the beta app only.
        with mock.patch.object(native_pin, "asset") as download:
            native_pin.main(["x", "bump", f"v0.{self.minor + 1}.0-beta.9"])
        download.assert_not_called()
        stable = self.files(self.stable)
        later = f"v0.{self.minor + 1}.1-beta.1"
        self.bump(later)
        self.assertEqual(native_pin.read_pin()[0], later)
        self.assertEqual(stable, self.files(self.stable))

    def test_later_stable_moves_and_older_is_ignored(self):
        self.bump(self.first)
        self.bump(self.second)
        self.assertEqual(native_pin.read_pin("stable")[0], self.second)
        before = self.files(self.stable)
        with mock.patch.object(native_pin, "asset") as download:
            native_pin.main(["x", "bump", self.first])
        download.assert_not_called()
        self.assertEqual(before, self.files(self.stable))

    def test_a_beta_never_moves_the_stable_app(self):
        stable = self.files(self.stable)
        self.bump(f"v0.{self.minor + 1}.0-beta.1")
        self.assertEqual(stable, self.files(self.stable))

    def test_the_stable_app_names_its_image_before_it_is_listed(self):
        manifest = self.stable / native_pin.UNLISTED
        self.assertEqual(native_pin.image(manifest.read_text()), native_pin.IMAGE)
        text = manifest.read_text()
        manifest.write_text(re.sub(r"(?m)^image:.*\n", "", text))
        with self.assertRaisesRegex(SystemExit, "must pull"):
            native_pin.read_pin("stable")
        manifest.write_text(text)
        self.bump(self.first)
        listed = (self.stable / "config.yaml").read_text()
        self.assertEqual(re.findall(r"(?m)^image:.*$", listed), [native_pin.IMAGE_LINE])

    def test_an_unlisted_app_with_a_pin_is_refused(self):
        build = self.stable / "Dockerfile"
        build.write_text(build.read_text().replace("ARG FTW_SHA256_AMD64=\n", f"ARG FTW_SHA256_AMD64={A}\n"))
        with self.assertRaisesRegex(SystemExit, "pin nothing"):
            native_pin.read_pin("stable")

    def test_one_manifest_only(self):
        self.bump(self.first)
        (self.stable / native_pin.UNLISTED).write_text((self.stable / "config.yaml").read_text())
        with self.assertRaisesRegex(SystemExit, "one manifest"):
            native_pin.read_pin("stable")

    def test_the_stable_app_never_holds_a_beta(self):
        self.bump(self.first)
        config, build = self.stable / "config.yaml", self.stable / "Dockerfile"
        beta = f"v0.{self.minor}.0-beta.1"
        config.write_text(config.read_text().replace(self.first[1:], beta[1:]).replace(self.first, beta))
        build.write_text(build.read_text().replace(self.first, beta))
        with self.assertRaisesRegex(SystemExit, "takes only stable"):
            native_pin.read_pin("stable")
        with self.assertRaisesRegex(SystemExit, "does not take"):
            native_pin.write_pin(beta, {"amd64": A, "arm64": B}, "stable")
