from __future__ import annotations

import json
import unittest
from unittest import mock

import yaml

from scripts import upstream_sync, validate


CORE_DIGEST = "sha256:" + "a" * 64
CORE_COMMIT = "b" * 40
OPTIMIZER_DIGEST = "sha256:" + "c" * 64
OPTIMIZER_COMMIT = "d" * 40


def release(tag: str, *, draft: bool = False, body: str = "") -> dict:
    return {
        "tag_name": tag,
        "draft": draft,
        "html_url": f"https://github.com/srcfl/ftw/releases/tag/{tag}",
        "body": body,
    }


def core_pin(
    version: str = "v1.11.0",
    body: str = "Live pilot: https://github.com/srcfl/ftw/pull/700#issuecomment-1",
) -> dict:
    return {
        "version": version,
        "digest": CORE_DIGEST,
        "commit": CORE_COMMIT,
        "release_url": f"https://github.com/srcfl/ftw/releases/tag/{version}",
        "build_url": "https://github.com/srcfl/ftw/actions/runs/1",
        "body": body,
    }


def optimizer_pin(version: str = "v1.4.0") -> dict:
    return {
        "version": version,
        "digest": OPTIMIZER_DIGEST,
        "commit": OPTIMIZER_COMMIT,
        "release_url": f"https://github.com/srcfl/ftw/releases/tag/optimizer-{version}",
        "build_url": None,
        "body": "",
    }


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


class ReleaseSelectionTests(unittest.TestCase):
    def test_highest_core_release_wins_and_drafts_are_ignored(self) -> None:
        releases = [
            release("v1.9.0"),
            release("v1.10.0-beta.1"),
            release("v1.12.0", draft=True),
            release("v1.11.0"),
            release("optimizer-v9.9.9"),
            release("nightly-build"),
        ]
        best = upstream_sync.select_latest_release(releases, upstream_sync.CORE_TAG)
        self.assertEqual(best["tag_name"], "v1.11.0")

    def test_optimizer_releases_use_their_own_line(self) -> None:
        releases = [
            release("v9.0.0"),
            release("optimizer-v1.3.2-beta.1"),
            release("optimizer-v1.4.0"),
        ]
        best = upstream_sync.select_latest_release(releases, upstream_sync.OPTIMIZER_TAG)
        self.assertEqual(best["tag_name"], "optimizer-v1.4.0")

    def test_no_matching_release_returns_none(self) -> None:
        self.assertIsNone(upstream_sync.select_latest_release([release("nightly")], upstream_sync.CORE_TAG))


class NextVersionTests(unittest.TestCase):
    def test_beta_bumps_the_beta_number(self) -> None:
        self.assertEqual(
            upstream_sync.next_add_on_version("0.1.0-beta.1", lambda tag: False),
            "0.1.0-beta.2",
        )

    def test_existing_tags_are_skipped(self) -> None:
        taken = {"ftw-v0.1.0-beta.2", "ftw-v0.1.0-beta.3"}
        self.assertEqual(
            upstream_sync.next_add_on_version("0.1.0-beta.1", lambda tag: tag in taken),
            "0.1.0-beta.4",
        )

    def test_stable_starts_the_next_patch_beta_line(self) -> None:
        self.assertEqual(
            upstream_sync.next_add_on_version("0.1.0", lambda tag: False),
            "0.1.1-beta.1",
        )

    def test_invalid_current_version_fails(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "invalid"):
            upstream_sync.next_add_on_version("0.1.0-rc.1", lambda tag: False)


class LivePilotEvidenceTests(unittest.TestCase):
    def test_labeled_live_pilot_link_wins(self) -> None:
        body = (
            "Notes with https://github.com/srcfl/ftw/pull/1 first.\n"
            "Live pilot: https://github.com/srcfl/ftw/pull/623#issuecomment-5042911361.\n"
        )
        self.assertEqual(
            upstream_sync.extract_live_pilot_evidence(body),
            "https://github.com/srcfl/ftw/pull/623#issuecomment-5042911361",
        )

    def test_unlabeled_pilot_url_is_rejected(self) -> None:
        body = "Qualified via https://github.com/srcfl/ftw/actions/runs/9?query=live-pilot-suite"
        self.assertIsNone(upstream_sync.extract_live_pilot_evidence(body))

    def test_labeled_action_run_is_accepted(self) -> None:
        body = "Live pilot: https://github.com/srcfl/ftw/actions/runs/9?query=live-pilot-suite"
        self.assertEqual(
            upstream_sync.extract_live_pilot_evidence(body),
            "https://github.com/srcfl/ftw/actions/runs/9?query=live-pilot-suite",
        )

    def test_labeled_release_page_is_not_pilot_evidence(self) -> None:
        body = "Live pilot: https://github.com/srcfl/ftw/releases/tag/v1.11.0"
        self.assertIsNone(upstream_sync.extract_live_pilot_evidence(body))

    def test_release_without_pilot_evidence_is_rejected(self) -> None:
        self.assertIsNone(upstream_sync.extract_live_pilot_evidence("no links here"))


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

    def test_optimizer_does_not_accept_the_core_base_label_contract(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "version label"):
            self.inspect(
                image=upstream_sync.OPTIMIZER_IMAGE,
                version="v1.4.0",
                version_label="1.4.0",
                commit=OPTIMIZER_COMMIT,
                digest=OPTIMIZER_DIGEST,
            )


class FileRewriteTests(unittest.TestCase):
    def test_config_version_is_replaced_in_place(self) -> None:
        text = (
            'name: FTW\nversion: "0.1.0-beta.1"\nslug: ftw\n'
            'environment:\n  FTW_BUNDLE_VERSION: "0.1.0-beta.1"\n'
        )
        self.assertEqual(
            upstream_sync.replace_config_version(text, "0.1.0-beta.2"),
            'name: FTW\nversion: "0.1.0-beta.2"\nslug: ftw\n'
            'environment:\n  FTW_BUNDLE_VERSION: "0.1.0-beta.2"\n',
        )

    def test_missing_version_line_fails(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "version line"):
            upstream_sync.replace_config_version(
                'name: FTW\nenvironment:\n  FTW_BUNDLE_VERSION: "0.1.0-beta.1"\n',
                "0.1.0-beta.2",
            )

    def test_missing_bundle_version_line_fails(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "FTW_BUNDLE_VERSION line"):
            upstream_sync.replace_config_version(
                'name: FTW\nversion: "0.1.0-beta.1"\n',
                "0.1.0-beta.2",
            )

    def test_changelog_entry_is_prepended_under_the_header(self) -> None:
        text = "# Changelog\n\n## 0.1.0-beta.1\n\n- Old entry.\n"
        updated = upstream_sync.prepend_changelog(text, "0.1.0-beta.2", core_pin(), None)
        self.assertTrue(updated.startswith("# Changelog\n\n## 0.1.0-beta.2\n\n- Update Core to v1.11.0.\n"))
        self.assertIn("## 0.1.0-beta.1", updated)


class ComposeUpdatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat = upstream_sync.load_yaml(upstream_sync.ROOT / "compatibility.yaml")
        self.config_text = (upstream_sync.ROOT / "ftw/config.yaml").read_text(encoding="utf-8")
        self.changelog_text = (upstream_sync.ROOT / "ftw/CHANGELOG.md").read_text(encoding="utf-8")
        self.new_version = upstream_sync.next_add_on_version(
            str(self.compat["add_on"]["version"]), lambda tag: False
        )

    def compose(self, *, core: dict | None, optimizer: dict | None) -> tuple[dict, str, str, dict]:
        return upstream_sync.compose_updates(
            compat=self.compat,
            config_text=self.config_text,
            changelog_text=self.changelog_text,
            core_pin=core,
            optimizer_pin=optimizer,
            new_version=self.new_version,
            update_from=None,
        )

    def test_composed_bump_passes_beta_channel_validation(self) -> None:
        body = "Live pilot: https://github.com/srcfl/ftw/pull/700#issuecomment-1"
        compat, config_text, changelog, pilot = self.compose(
            core=core_pin(body=body), optimizer=optimizer_pin()
        )
        config = yaml.safe_load(config_text)
        original = validate.load_yaml
        with mock.patch.object(
            validate,
            "load_yaml",
            side_effect=lambda path: pilot if path.name == f"{self.new_version}.yaml" else original(path),
        ):
            validate.validate_common(config, compat)
            validate.validate_channel("beta", config, compat)
        self.assertIn(f"## {self.new_version}", changelog)

    def test_core_bump_without_labeled_live_pilot_fails_closed(self) -> None:
        with self.assertRaisesRegex(upstream_sync.SyncError, "live-pilot evidence"):
            self.compose(core=core_pin(body=""), optimizer=None)

    def test_round_tripped_yaml_passes_the_same_validation(self) -> None:
        compat, config_text, _, pilot = self.compose(core=core_pin(), optimizer=optimizer_pin())
        compat = yaml.safe_load(upstream_sync.dump_yaml(compat))
        pilot = yaml.safe_load(upstream_sync.dump_yaml(pilot))
        config = yaml.safe_load(config_text)
        original = validate.load_yaml
        with mock.patch.object(
            validate,
            "load_yaml",
            side_effect=lambda path: pilot if path.name == f"{self.new_version}.yaml" else original(path),
        ):
            validate.validate_common(config, compat)
            validate.validate_channel("beta", config, compat)

    def test_core_only_bump_keeps_the_optimizer_pins_and_evidence(self) -> None:
        compat, _, _, _ = self.compose(core=core_pin(), optimizer=None)
        self.assertEqual(compat["optimizer"]["version"], self.compat["optimizer"]["version"])
        self.assertEqual(compat["optimizer"]["digest"], self.compat["optimizer"]["digest"])
        self.assertEqual(
            compat["qualification"]["upstream_gate"]["evidence"]["optimizer_release"],
            self.compat["qualification"]["upstream_gate"]["evidence"]["optimizer_release"],
        )
        self.assertEqual(compat["core"]["version"], "v1.11.0")
        self.assertEqual(compat["core"]["digest"], CORE_DIGEST)

    def test_bump_resets_the_publisher_marker_and_promotion_record(self) -> None:
        compat, _, _, _ = self.compose(core=core_pin(), optimizer=optimizer_pin())
        self.assertEqual(compat["add_on"]["manifest_digest"], upstream_sync.PUBLISHER_MARKER)
        self.assertEqual(
            compat["qualification"]["promoted_from_beta"],
            {"channel": None, "version": None, "manifest_digest": None, "source_commit": None},
        )
        self.assertEqual(
            compat["qualification"]["home_assistant_os_supervisor"]["record"],
            f"pilot/{self.new_version}.yaml",
        )

    def test_pilot_record_mirrors_the_new_pins(self) -> None:
        compat, _, _, pilot = self.compose(core=core_pin(), optimizer=optimizer_pin())
        self.assertEqual(pilot["add_on_version"], self.new_version)
        self.assertEqual(pilot["candidate"]["core"]["digest"], compat["core"]["digest"])
        self.assertEqual(pilot["candidate"]["optimizer"]["commit"], compat["optimizer"]["commit"])
        self.assertEqual(pilot["checks"]["update"]["to_version"], self.new_version)
        self.assertEqual(pilot["checks"]["rollback"]["from_version"], self.new_version)


class ResolvePinTests(unittest.TestCase):
    def test_unchanged_version_is_skipped_without_network_calls(self) -> None:
        with mock.patch.object(upstream_sync, "gh_api", side_effect=AssertionError("no API call")):
            self.assertIsNone(
                upstream_sync.resolve_pin(
                    upstream="srcfl/ftw",
                    release=release("v1.10.0-beta.1"),
                    image=upstream_sync.CORE_IMAGE,
                    current_version="v1.10.0-beta.1",
                )
            )

    def test_downgrades_are_skipped(self) -> None:
        with mock.patch.object(upstream_sync, "gh_api", side_effect=AssertionError("no API call")):
            self.assertIsNone(
                upstream_sync.resolve_pin(
                    upstream="srcfl/ftw",
                    release=release("v1.9.0"),
                    image=upstream_sync.CORE_IMAGE,
                    current_version="v1.10.0-beta.1",
                )
            )

    def test_new_release_pins_the_verified_digest_and_commit(self) -> None:
        with (
            mock.patch.object(upstream_sync, "gh_api", return_value={"sha": CORE_COMMIT}),
            mock.patch.object(upstream_sync, "inspect_release_image", return_value=CORE_DIGEST),
            mock.patch.object(upstream_sync, "discover_build_run", return_value=None),
        ):
            pin = upstream_sync.resolve_pin(
                upstream="srcfl/ftw",
                release=release("v1.11.0"),
                image=upstream_sync.CORE_IMAGE,
                current_version="v1.10.0-beta.1",
            )
        self.assertEqual(pin["version"], "v1.11.0")
        self.assertEqual(pin["digest"], CORE_DIGEST)
        self.assertEqual(pin["commit"], CORE_COMMIT)


if __name__ == "__main__":
    unittest.main()
