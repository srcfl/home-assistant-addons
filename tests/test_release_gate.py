from __future__ import annotations

import copy
import json
import pathlib
import unittest

from scripts import release_gate


FIXTURES = pathlib.Path(__file__).parent / "fixtures/release"
DIGEST = "sha256:" + "d" * 64
COMMIT = "e" * 40


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def compatibility() -> dict:
    return {
        "add_on": {
            "image": "ghcr.io/srcfl/home-assistant-addons/ftw",
            "manifest_digest": DIGEST,
        },
        "qualification": {
            "promoted_from_beta": {
                "channel": "beta",
                "version": "0.1.0-beta.1",
                "manifest_digest": DIGEST,
                "source_commit": COMMIT,
            }
        },
    }


class BetaTargetTests(unittest.TestCase):
    def test_unused_target_passes(self) -> None:
        release_gate.validate_beta_target_state(
            git_tag_exists=False, release_exists=False, image_digest=None
        )

    def test_existing_git_tag_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "Git tag"):
            release_gate.validate_beta_target_state(
                git_tag_exists=True, release_exists=False, image_digest=None
            )

    def test_existing_release_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "GitHub release"):
            release_gate.validate_beta_target_state(
                git_tag_exists=False, release_exists=True, image_digest=None
            )

    def test_existing_version_image_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "image version tag"):
            release_gate.validate_beta_target_state(
                git_tag_exists=False, release_exists=False, image_digest=DIGEST
            )


class ImageEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = fixture("index.json")
        self.images = {
            "amd64": fixture("image-amd64.json"),
            "arm64": fixture("image-arm64.json"),
        }

    def validate(self) -> None:
        release_gate.validate_image_platforms(
            name="Fixture",
            index=self.index,
            platform_images=self.images,
            expected_version="v1.2.3-beta.1",
            expected_commit="c" * 40,
        )

    def test_both_architectures_and_labels_pass(self) -> None:
        self.validate()

    def test_missing_architecture_fails(self) -> None:
        self.index["manifests"].pop()
        with self.assertRaisesRegex(release_gate.GateError, "linux/arm64"):
            self.validate()

    def test_wrong_version_label_fails(self) -> None:
        self.images["arm64"]["config"]["Labels"]["org.opencontainers.image.version"] = "wrong"
        with self.assertRaisesRegex(release_gate.GateError, "version label"):
            self.validate()

    def test_wrong_revision_label_fails(self) -> None:
        self.images["amd64"]["config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40
        with self.assertRaisesRegex(release_gate.GateError, "revision label"):
            self.validate()


class StableGateTests(unittest.TestCase):
    def test_missing_stable_tag_can_be_created(self) -> None:
        self.assertFalse(release_gate.validate_stable_tag(None, DIGEST))

    def test_matching_stable_tag_is_idempotent(self) -> None:
        self.assertTrue(release_gate.validate_stable_tag(DIGEST, DIGEST))

    def test_different_stable_tag_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "different digest"):
            release_gate.validate_stable_tag("sha256:" + "a" * 64, DIGEST)

    def test_beta_release_record_passes(self) -> None:
        image, source_commit = release_gate.validate_beta_release_record(
            manifest=fixture("beta-release-manifest.json"),
            compatibility=compatibility(),
            beta_version="0.1.0-beta.1",
            beta_digest=DIGEST,
        )
        self.assertEqual(image, "ghcr.io/srcfl/home-assistant-addons/ftw")
        self.assertEqual(source_commit, COMMIT)

    def test_each_beta_release_field_mismatch_fails(self) -> None:
        values = {
            "channel": "stable",
            "version": "0.1.0-beta.2",
            "manifest_digest": "sha256:" + "a" * 64,
            "source_commit": "f" * 40,
        }
        for field, value in values.items():
            with self.subTest(field=field):
                manifest = fixture("beta-release-manifest.json")
                manifest[field] = value
                with self.assertRaisesRegex(release_gate.GateError, field):
                    release_gate.validate_beta_release_record(
                        manifest=manifest,
                        compatibility=compatibility(),
                        beta_version="0.1.0-beta.1",
                        beta_digest=DIGEST,
                    )

    def test_compatibility_source_commit_mismatch_fails(self) -> None:
        compat = compatibility()
        compat["qualification"]["promoted_from_beta"]["source_commit"] = "f" * 40
        with self.assertRaisesRegex(release_gate.GateError, "source_commit"):
            release_gate.validate_beta_release_record(
                manifest=fixture("beta-release-manifest.json"),
                compatibility=compat,
                beta_version="0.1.0-beta.1",
                beta_digest=DIGEST,
            )

    def test_each_compatibility_beta_field_mismatch_fails(self) -> None:
        values = {
            "channel": "stable",
            "version": "0.1.0-beta.2",
            "manifest_digest": "sha256:" + "a" * 64,
            "source_commit": "f" * 40,
        }
        for field, value in values.items():
            with self.subTest(field=field):
                compat = compatibility()
                compat["qualification"]["promoted_from_beta"][field] = value
                with self.assertRaisesRegex(release_gate.GateError, field):
                    release_gate.validate_beta_release_record(
                        manifest=fixture("beta-release-manifest.json"),
                        compatibility=compat,
                        beta_version="0.1.0-beta.1",
                        beta_digest=DIGEST,
                    )


class ExistingReleaseTests(unittest.TestCase):
    def test_equal_json_is_idempotent(self) -> None:
        release_gate.validate_same_json(
            fixture("beta-release-manifest.json"), copy.deepcopy(fixture("beta-release-manifest.json"))
        )

    def test_different_json_fails_closed(self) -> None:
        actual = fixture("beta-release-manifest.json")
        actual["source_commit"] = "f" * 40
        with self.assertRaisesRegex(release_gate.GateError, "existing release manifest"):
            release_gate.validate_same_json(fixture("beta-release-manifest.json"), actual)


if __name__ == "__main__":
    unittest.main()
