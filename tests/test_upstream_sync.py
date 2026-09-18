from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

import yaml

from scripts import upstream_sync, validate


CORE_DIGEST = "sha256:" + "a" * 64
CORE_COMMIT = "b" * 40
ADD_ON_DIGEST = "sha256:" + "d" * 64
ADD_ON_COMMIT = "e" * 40


def release(tag: str, *, draft: bool = False, prerelease: bool | None = None) -> dict:
    if prerelease is None:
        prerelease = "-beta." in tag
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/srcfl/ftw/releases/tag/{tag}",
    }


def receipt(
    tag: str,
    *,
    channel: str = "beta",
    source_beta: str | None = None,
    digest: str = CORE_DIGEST,
    commit: str = CORE_COMMIT,
) -> bytes:
    value: dict = {
        "schema": 1,
        "commit": commit,
        "stable_version": tag.removeprefix("v").split("-beta.")[0],
        "images": {"core": {"digest": digest}, "updater": {"digest": "sha256:" + "f" * 64}},
    }
    if channel == "beta":
        value["tag"] = tag
    else:
        value["stable_tag"] = tag
        value["source_beta"] = source_beta or f"{tag}-beta.1"
    return json.dumps(value).encode()


def core_pin(version: str = "v3.5.0-beta.1", *, source_beta: str | None = None) -> dict:
    return {
        "version": version,
        "commit": CORE_COMMIT,
        "digest": CORE_DIGEST,
        "release_url": f"https://github.com/srcfl/ftw/releases/tag/{version}",
        "source_beta": source_beta or version,
    }


def baseline() -> dict:
    return {
        "commit": "c" * 40,
        "manifest_sha256": "1" * 64,
        "key_id": "ftw-drivers-2026-01",
        "evidence": {
            "commit": "https://github.com/srcfl/device-drivers/commit/" + "c" * 40,
            "release": "https://github.com/srcfl/device-drivers/releases/tag/drivers-stable",
        },
    }


def add_on_beta(version: str, *, core_digest: str = CORE_DIGEST) -> dict:
    return {
        "schema_version": 2,
        "channel": "beta",
        "version": version,
        "image": "ghcr.io/srcfl/home-assistant-addons/ftw",
        "manifest_digest": ADD_ON_DIGEST,
        "source_commit": ADD_ON_COMMIT,
        "core": {"version": f"v{version}", "digest": core_digest, "commit": CORE_COMMIT},
    }


def load_repository() -> tuple[dict, str, str]:
    root = upstream_sync.ROOT
    return (
        upstream_sync.load_yaml(root / "compatibility.yaml"),
        (root / "ftw-beta/config.yaml").read_text(encoding="utf-8"),
        (root / "ftw-beta/CHANGELOG.md").read_text(encoding="utf-8"),
    )


def with_passed_pilot(compat: dict) -> dict:
    compat = copy.deepcopy(compat)
    compat["qualification"]["home_assistant_os_supervisor"].update(
        status="passed",
        add_on_version="3.4.2-beta.4",
        evidence="https://github.com/srcfl/home-assistant-addons/issues/1",
    )
    return compat


class VersionOrderingTests(unittest.TestCase):
    def test_final_release_outranks_its_betas(self) -> None:
        self.assertGreater(
            upstream_sync.version_key("v1.10.0"),
            upstream_sync.version_key("v1.10.0-beta.2"),
        )

    def test_beta_numbers_order_numerically(self) -> None:
        self.assertGreater(
            upstream_sync.version_key("v1.10.0-beta.10"),
            upstream_sync.version_key("v1.10.0-beta.9"),
        )

    def test_invalid_versions_are_rejected(self) -> None:
        for version in ("1.10.0", "v1.10", "v1.10.0-rc.1", "v1.10.0-beta"):
            with self.subTest(version=version):
                self.assertIsNone(upstream_sync.version_key(version))


class AddOnVersionTests(unittest.TestCase):
    def test_app_version_mirrors_the_core_version(self) -> None:
        self.assertEqual(upstream_sync.add_on_version("v3.4.2-beta.4"), "3.4.2-beta.4")
        self.assertEqual(upstream_sync.add_on_version("v3.4.2"), "3.4.2")

    def test_invalid_core_version_fails(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "invalid"):
            upstream_sync.add_on_version("3.4.2")


class ReleaseSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.releases = [
            release("v1.9.0"),
            release("v1.10.0-beta.1"),
            release("v1.12.0", draft=True),
            release("v1.11.0"),
            release("v2.0.0-beta.3"),
            release("v2.0.0-beta.2"),
            release("nightly-build"),
            release("optimizer-v9.9.9"),
            release("v3.0.0", prerelease=True),
            release("v3.1.0-beta.1", prerelease=False),
        ]

    def test_beta_channel_takes_the_highest_prerelease_beta(self) -> None:
        best = upstream_sync.select_latest_release(self.releases, "beta")
        self.assertEqual(best["tag_name"], "v2.0.0-beta.3")

    def test_stable_channel_takes_the_highest_final_release(self) -> None:
        best = upstream_sync.select_latest_release(self.releases, "stable")
        self.assertEqual(best["tag_name"], "v1.11.0")

    def test_no_matching_release_returns_none(self) -> None:
        self.assertIsNone(upstream_sync.select_latest_release([release("nightly")], "beta"))
        self.assertIsNone(upstream_sync.select_latest_release([release("v1.0.0-beta.1")], "stable"))


class ReceiptTests(unittest.TestCase):
    def test_beta_receipt_yields_the_core_digest(self) -> None:
        parsed = upstream_sync.parse_receipt(
            receipt("v3.5.0-beta.1"), channel="beta", tag="v3.5.0-beta.1", commit=CORE_COMMIT
        )
        self.assertEqual(parsed, {"digest": CORE_DIGEST, "source_beta": "v3.5.0-beta.1"})

    def test_stable_receipt_names_its_source_beta(self) -> None:
        parsed = upstream_sync.parse_receipt(
            receipt("v3.4.2", channel="stable", source_beta="v3.4.2-beta.4"),
            channel="stable",
            tag="v3.4.2",
            commit=CORE_COMMIT,
        )
        self.assertEqual(parsed, {"digest": CORE_DIGEST, "source_beta": "v3.4.2-beta.4"})

    def test_receipt_mismatches_fail(self) -> None:
        cases = {
            "different tag": (receipt("v3.5.0-beta.2"), "beta", "v3.5.0-beta.1", CORE_COMMIT),
            "commit differs": (receipt("v3.5.0-beta.1"), "beta", "v3.5.0-beta.1", "f" * 40),
            "different stable tag": (receipt("v3.5.0-beta.1"), "stable", "v3.5.0-beta.1", CORE_COMMIT),
            "Core digest": (receipt("v3.5.0-beta.1", digest="oops"), "beta", "v3.5.0-beta.1", CORE_COMMIT),
            "schema": (b'{"schema": 2}', "beta", "v3.5.0-beta.1", CORE_COMMIT),
            "not valid JSON": (b"{", "beta", "v3.5.0-beta.1", CORE_COMMIT),
        }
        for message, (raw, channel, tag, commit) in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(upstream_sync.SyncError, message):
                    upstream_sync.parse_receipt(raw, channel=channel, tag=tag, commit=commit)


class ReleaseImageContractTests(unittest.TestCase):
    def inspect(
        self,
        *,
        image: str,
        version: str,
        version_label: str | None,
        commit: str = CORE_COMMIT,
        digest: str = CORE_DIGEST,
    ) -> str:
        index = {
            "manifests": [
                {"digest": "sha256:" + "1" * 64, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:" + "2" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
            ]
        }
        labels = {"org.opencontainers.image.revision": commit}
        if version_label is not None:
            labels["org.opencontainers.image.version"] = version_label
        child = {"config": {"Labels": labels}}
        with (
            mock.patch.object(upstream_sync, "optional_image_digest", return_value=digest),
            mock.patch.object(
                upstream_sync,
                "command_output",
                side_effect=(json.dumps(index), json.dumps(child), json.dumps(child)),
            ),
        ):
            return upstream_sync.inspect_release_image(image, version, commit)

    def test_legacy_and_current_core_labels_accept_beta_and_stable(self) -> None:
        cases = (
            ("v1.16.1-beta.20", "v1.16.1-beta.20"),
            ("v1.15.0", "1.15.0"),
            ("v2.0.0-beta.3", "2.0.0"),
            ("v2.0.0", "2.0.0"),
        )
        for version, label in cases:
            with self.subTest(version=version, label=label):
                self.assertEqual(
                    self.inspect(image=upstream_sync.CORE_IMAGE, version=version, version_label=label),
                    CORE_DIGEST,
                )

    def test_wrong_core_base_or_candidate_label_fails(self) -> None:
        for label in ("2.0.1", "v2.0.0", "1.16.1-beta.21", "v2.0.0-beta.2", None):
            with self.subTest(label=label):
                with self.assertRaisesRegex(upstream_sync.SyncError, "version label"):
                    self.inspect(
                        image=upstream_sync.CORE_IMAGE,
                        version="v2.0.0-beta.3",
                        version_label=label,
                    )

    def test_stable_rejects_prefixed_or_candidate_labels(self) -> None:
        for label in ("v2.0.0", "v2.0.0-beta.3", "2.0.0-beta.3"):
            with self.subTest(label=label):
                with self.assertRaisesRegex(upstream_sync.SyncError, "version label"):
                    self.inspect(
                        image=upstream_sync.CORE_IMAGE,
                        version="v2.0.0",
                        version_label=label,
                    )

    def test_wrong_revision_label_fails(self) -> None:
        index = {
            "manifests": [
                {"digest": "sha256:" + "1" * 64, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:" + "2" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
            ]
        }
        child = {
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": "f" * 40,
                    "org.opencontainers.image.version": "2.0.0",
                }
            }
        }
        with (
            mock.patch.object(upstream_sync, "optional_image_digest", return_value=CORE_DIGEST),
            mock.patch.object(
                upstream_sync,
                "command_output",
                side_effect=(json.dumps(index), json.dumps(child), json.dumps(child)),
            ),
        ):
            with self.assertRaisesRegex(upstream_sync.SyncError, "revision label"):
                upstream_sync.inspect_release_image(upstream_sync.CORE_IMAGE, "v2.0.0", CORE_COMMIT)

    def test_missing_image_is_retried_later(self) -> None:
        with mock.patch.object(upstream_sync, "optional_image_digest", return_value=None):
            with self.assertRaises(upstream_sync.ImageNotReady):
                upstream_sync.inspect_release_image(upstream_sync.CORE_IMAGE, "v2.0.0", CORE_COMMIT)


class ResolvePinTests(unittest.TestCase):
    def resolve(self, tag: str, *, current: str, channel: str = "beta", registry_digest: str = CORE_DIGEST) -> dict | None:
        with (
            mock.patch.object(upstream_sync, "gh_api", return_value={"sha": CORE_COMMIT}),
            mock.patch.object(
                upstream_sync,
                "download_release_asset",
                return_value=receipt(tag, channel=channel, source_beta="v3.4.2-beta.4"),
            ),
            mock.patch.object(upstream_sync, "inspect_release_image", return_value=registry_digest),
        ):
            return upstream_sync.resolve_core_pin(
                upstream="srcfl/ftw",
                release=release(tag),
                channel=channel,
                current_version=current,
            )

    def test_unchanged_version_is_skipped_without_network_calls(self) -> None:
        with mock.patch.object(upstream_sync, "gh_api", side_effect=AssertionError("no API call")):
            self.assertIsNone(
                upstream_sync.resolve_core_pin(
                    upstream="srcfl/ftw",
                    release=release("v3.4.2-beta.4"),
                    channel="beta",
                    current_version="v3.4.2-beta.4",
                )
            )

    def test_downgrades_are_skipped(self) -> None:
        with mock.patch.object(upstream_sync, "gh_api", side_effect=AssertionError("no API call")):
            self.assertIsNone(
                upstream_sync.resolve_core_pin(
                    upstream="srcfl/ftw",
                    release=release("v3.4.2-beta.3"),
                    channel="beta",
                    current_version="v3.4.2-beta.4",
                )
            )

    def test_new_release_pins_the_receipt_verified_digest(self) -> None:
        pin = self.resolve("v3.5.0-beta.1", current="v3.4.2-beta.4")
        self.assertEqual(pin["version"], "v3.5.0-beta.1")
        self.assertEqual(pin["digest"], CORE_DIGEST)
        self.assertEqual(pin["commit"], CORE_COMMIT)
        self.assertEqual(pin["source_beta"], "v3.5.0-beta.1")

    def test_empty_current_version_accepts_the_first_stable(self) -> None:
        pin = self.resolve("v3.4.2", current="", channel="stable")
        self.assertEqual(pin["version"], "v3.4.2")
        self.assertEqual(pin["source_beta"], "v3.4.2-beta.4")

    def test_registry_digest_must_match_the_receipt(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "release receipt"):
            self.resolve("v3.5.0-beta.1", current="v3.4.2-beta.4", registry_digest="sha256:" + "9" * 64)

    def test_missing_receipt_is_retried_later(self) -> None:
        with (
            mock.patch.object(upstream_sync, "gh_api", return_value={"sha": CORE_COMMIT}),
            mock.patch.object(
                upstream_sync,
                "download_release_asset",
                side_effect=upstream_sync.ImageNotReady("no receipt yet"),
            ),
        ):
            with self.assertRaises(upstream_sync.ImageNotReady):
                upstream_sync.resolve_core_pin(
                    upstream="srcfl/ftw",
                    release=release("v3.5.0-beta.1"),
                    channel="beta",
                    current_version="v3.4.2-beta.4",
                )


class FileRewriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat, self.beta_text, _ = load_repository()

    def test_config_version_lines_are_replaced_in_place(self) -> None:
        updated = upstream_sync.replace_config_version(self.beta_text, "3.5.0-beta.1", "v3.5.0-beta.1")
        before = yaml.safe_load(self.beta_text)
        after = yaml.safe_load(updated)
        self.assertEqual(after["version"], "3.5.0-beta.1")
        self.assertEqual(after["environment"]["FTW_BUNDLE_VERSION"], "3.5.0-beta.1")
        self.assertEqual(after["environment"]["FTW_IMAGE_TAG"], "v3.5.0-beta.1")
        for key in ("version",):
            before.pop(key)
            after.pop(key)
        for key in ("FTW_BUNDLE_VERSION", "FTW_IMAGE_TAG"):
            before["environment"].pop(key)
            after["environment"].pop(key)
        self.assertEqual(before, after)

    def test_missing_lines_fail(self) -> None:
        cases = {
            "version": self.beta_text.replace('version: "3.4.2-beta.4"\n', "", 1),
            "FTW_BUNDLE_VERSION": self.beta_text.replace('  FTW_BUNDLE_VERSION: "3.4.2-beta.4"\n', "", 1),
            "FTW_IMAGE_TAG": self.beta_text.replace("  FTW_IMAGE_TAG: v3.4.2-beta.4\n", "", 1),
        }
        for name, text in cases.items():
            with self.subTest(line=name):
                with self.assertRaisesRegex(upstream_sync.SyncError, name):
                    upstream_sync.replace_config_version(text, "3.5.0-beta.1", "v3.5.0-beta.1")

    def test_stable_config_derives_from_the_beta_manifest(self) -> None:
        rendered = upstream_sync.render_stable_config(self.beta_text, "3.4.2", "v3.4.2")
        config = yaml.safe_load(rendered)
        self.assertEqual(config["name"], "FTW")
        self.assertEqual(config["slug"], "ftw")
        self.assertEqual(config["url"], "https://github.com/srcfl/home-assistant-addons/tree/main/ftw")
        self.assertEqual(config["version"], "3.4.2")
        self.assertEqual(config["environment"]["FTW_IMAGE_TAG"], "v3.4.2")
        self.assertNotIn("stage", config)
        self.assertTrue(config["host_network"])

    def test_changelog_entry_is_prepended_under_the_header(self) -> None:
        text = "# Changelog\n\n## 1.0.0-beta.1\n\n- Old entry.\n"
        updated = upstream_sync.prepend_changelog(text, "1.0.0-beta.2", ["New entry."])
        self.assertTrue(updated.startswith("# Changelog\n\n## 1.0.0-beta.2\n\n- New entry.\n\n## 1.0.0-beta.1"))
        self.assertEqual(
            upstream_sync.prepend_changelog("# Changelog\n", "1.0.0", ["First."]),
            "# Changelog\n\n## 1.0.0\n\n- First.\n",
        )


class ComposeUpdatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat, self.beta_text, self.beta_changelog = load_repository()

    def test_beta_update_passes_validation(self) -> None:
        compat, config_text, changelog = upstream_sync.compose_beta_update(
            compat=self.compat,
            config_text=self.beta_text,
            changelog_text=self.beta_changelog,
            pin=core_pin("v3.5.0-beta.1"),
            baseline=baseline(),
        )
        validate.validate_common(compat)
        validate.validate_beta(compat)
        validate.validate_add_on_config(yaml.safe_load(config_text), compat, "beta")
        self.assertEqual(compat["beta"]["version"], "3.5.0-beta.1")
        self.assertEqual(compat["drivers"]["tested_baseline"], baseline())
        self.assertIn("## 3.5.0-beta.1", changelog)
        self.assertEqual(self.compat["beta"]["version"], "3.4.2-beta.4")

    def test_round_tripped_yaml_passes_the_same_validation(self) -> None:
        compat, config_text, _ = upstream_sync.compose_beta_update(
            compat=self.compat,
            config_text=self.beta_text,
            changelog_text=self.beta_changelog,
            pin=core_pin("v3.5.0-beta.1"),
            baseline=baseline(),
        )
        compat = yaml.safe_load(upstream_sync.dump_yaml(compat))
        validate.validate_common(compat)
        validate.validate_beta(compat)
        validate.validate_add_on_config(yaml.safe_load(config_text), compat, "beta")

    def test_stable_update_passes_validation(self) -> None:
        compat, config_text, changelog = upstream_sync.compose_stable_update(
            compat=with_passed_pilot(self.compat),
            beta_config_text=self.beta_text,
            changelog_text="# Changelog\n",
            pin=core_pin("v3.4.2", source_beta="v3.4.2-beta.4"),
            add_on_beta=add_on_beta("3.4.2-beta.4"),
        )
        validate.validate_common(compat)
        validate.validate_stable(compat, required=True)
        validate.validate_add_on_config(yaml.safe_load(config_text), compat, "stable")
        self.assertEqual(compat["stable"]["promoted_from_beta"], "3.4.2-beta.4")
        self.assertEqual(compat["stable"]["manifest_digest"], ADD_ON_DIGEST)
        self.assertIn("## 3.4.2", changelog)

    def test_stable_update_rejects_a_different_source_beta(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "promoted from"):
            upstream_sync.compose_stable_update(
                compat=with_passed_pilot(self.compat),
                beta_config_text=self.beta_text,
                changelog_text="# Changelog\n",
                pin=core_pin("v3.4.2", source_beta="v3.4.2-beta.4"),
                add_on_beta=add_on_beta("3.4.2-beta.3"),
            )

    def test_stable_update_rejects_a_different_core_digest(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "built from Core"):
            upstream_sync.compose_stable_update(
                compat=with_passed_pilot(self.compat),
                beta_config_text=self.beta_text,
                changelog_text="# Changelog\n",
                pin=core_pin("v3.4.2", source_beta="v3.4.2-beta.4"),
                add_on_beta=add_on_beta("3.4.2-beta.4", core_digest="sha256:" + "9" * 64),
            )


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat, self.beta_text, self.beta_changelog = load_repository()
        self.releases = [
            release("v3.5.0-beta.1"),
            release("v3.4.2"),
            release("v9.0.0", draft=True),
        ]

    def plan(self, **overrides: object) -> dict:
        kwargs: dict = {
            "repository": "srcfl/home-assistant-addons",
            "upstream": "srcfl/ftw",
            "compat": self.compat,
            "beta_config_text": self.beta_text,
            "beta_changelog_text": self.beta_changelog,
            "stable_changelog_text": "# Changelog\n",
            "releases": self.releases,
        }
        kwargs.update(overrides)
        return upstream_sync.plan(**kwargs)

    def test_blocked_pilot_pins_only_the_beta(self) -> None:
        def resolve(*, upstream: str, release: dict, channel: str, current_version: str) -> dict:
            self.assertEqual(channel, "beta")
            self.assertEqual(current_version, "v3.4.2-beta.4")
            return core_pin("v3.5.0-beta.1")

        with (
            mock.patch.object(upstream_sync, "resolve_core_pin", side_effect=resolve),
            mock.patch.object(upstream_sync, "current_driver_baseline", return_value=baseline()),
        ):
            planned = self.plan()
        self.assertEqual(planned["changed"], ["beta"])
        self.assertEqual(planned["compat"]["beta"]["version"], "3.5.0-beta.1")
        self.assertEqual(set(planned["files"]), {"ftw-beta/config.yaml", "ftw-beta/CHANGELOG.md"})

    def test_passed_pilot_waits_for_the_app_beta(self) -> None:
        def resolve(*, upstream: str, release: dict, channel: str, current_version: str) -> dict | None:
            if channel == "beta":
                return None
            return core_pin("v3.4.2", source_beta="v3.4.2-beta.4")

        with (
            mock.patch.object(upstream_sync, "resolve_core_pin", side_effect=resolve),
            mock.patch.object(upstream_sync, "add_on_beta_release", return_value=None),
        ):
            planned = self.plan(compat=with_passed_pilot(self.compat))
        self.assertEqual(planned["changed"], [])
        self.assertIsNone(planned["compat"]["stable"]["version"])

    def test_passed_pilot_promotes_the_matching_app_beta(self) -> None:
        def resolve(*, upstream: str, release: dict, channel: str, current_version: str) -> dict | None:
            if channel == "beta":
                return None
            self.assertEqual(current_version, "")
            return core_pin("v3.4.2", source_beta="v3.4.2-beta.4")

        with (
            mock.patch.object(upstream_sync, "resolve_core_pin", side_effect=resolve),
            mock.patch.object(upstream_sync, "add_on_beta_release", return_value=add_on_beta("3.4.2-beta.4")),
        ):
            planned = self.plan(compat=with_passed_pilot(self.compat))
        self.assertEqual(planned["changed"], ["stable"])
        self.assertEqual(planned["compat"]["stable"]["version"], "3.4.2")
        self.assertEqual(set(planned["files"]), {"ftw/config.yaml", "ftw/CHANGELOG.md"})
        validate.validate_stable(planned["compat"], required=True)
        validate.validate_add_on_config(yaml.safe_load(planned["files"]["ftw/config.yaml"]), planned["compat"], "stable")

    def test_beta_and_stable_can_land_in_one_run(self) -> None:
        def resolve(*, upstream: str, release: dict, channel: str, current_version: str) -> dict:
            if channel == "beta":
                return core_pin("v3.5.0-beta.1")
            return core_pin("v3.4.2", source_beta="v3.4.2-beta.4")

        with (
            mock.patch.object(upstream_sync, "resolve_core_pin", side_effect=resolve),
            mock.patch.object(upstream_sync, "current_driver_baseline", return_value=baseline()),
            mock.patch.object(upstream_sync, "add_on_beta_release", return_value=add_on_beta("3.4.2-beta.4")),
        ):
            planned = self.plan(compat=with_passed_pilot(self.compat))
        self.assertEqual(planned["changed"], ["beta", "stable"])
        validate.validate_common(planned["compat"])
        validate.validate_beta(planned["compat"])
        validate.validate_stable(planned["compat"], required=True)

    def test_unready_upstream_beta_is_retried_later(self) -> None:
        with mock.patch.object(
            upstream_sync, "resolve_core_pin", side_effect=upstream_sync.ImageNotReady("not yet")
        ):
            planned = self.plan()
        self.assertEqual(planned["changed"], [])

    def test_nothing_new_changes_nothing(self) -> None:
        with mock.patch.object(upstream_sync, "resolve_core_pin", return_value=None):
            planned = self.plan(compat=with_passed_pilot(self.compat))
        self.assertEqual(planned["changed"], [])
        self.assertEqual(planned["files"], {})


if __name__ == "__main__":
    unittest.main()
