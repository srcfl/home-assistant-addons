from __future__ import annotations

import copy
import unittest
from unittest import mock

from scripts import validate


APP_DIGEST = "sha256:" + "d" * 64
PRIOR_DIGEST = "sha256:" + "c" * 64
SOURCE_COMMIT = "e" * 40


class CoreImageVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = (validate.ROOT / "ftw/Dockerfile").read_text(encoding="utf-8")

    def test_beta_and_stable_core_versions_use_the_image_tag_contract(self) -> None:
        validate.validate_core_image_tag_contract(self.dockerfile)
        for version in ("v1.16.1-beta.20", "v1.16.1"):
            with self.subTest(version=version):
                compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")
                compat["core"]["version"] = version
                validate.require_release_values(compat, require_app_digest=False)
                rendered = self.dockerfile.replace("${CORE_VERSION}", version)
                self.assertIn(f"FTW_IMAGE_TAG={version}", rendered)

    def test_add_on_version_cannot_replace_core_version(self) -> None:
        dockerfile = self.dockerfile.replace(
            "FTW_IMAGE_TAG=${CORE_VERSION}",
            "FTW_IMAGE_TAG=${BUILD_VERSION}",
        )
        with self.assertRaisesRegex(validate.ValidationError, "must set FTW_IMAGE_TAG from CORE_VERSION"):
            validate.validate_core_image_tag_contract(dockerfile)


class BundleVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = validate.load_yaml(validate.ROOT / "ftw/config.yaml")
        self.compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")

    def test_beta_config_supplies_its_exact_runtime_version(self) -> None:
        validate.validate_common(self.config, self.compat)
        self.assertEqual(
            self.config["environment"]["FTW_BUNDLE_VERSION"],
            self.config["version"],
        )

    def test_stable_promotion_supplies_stable_runtime_version(self) -> None:
        stable = str(self.config["version"]).split("-beta.", 1)[0]
        config = copy.deepcopy(self.config)
        compat = copy.deepcopy(self.compat)
        config["version"] = stable
        config["environment"]["FTW_BUNDLE_VERSION"] = stable
        compat["add_on"]["version"] = stable
        validate.validate_common(config, compat)

    def test_stable_promotion_rejects_the_baked_beta_fallback(self) -> None:
        stable = str(self.config["version"]).split("-beta.", 1)[0]
        config = copy.deepcopy(self.config)
        compat = copy.deepcopy(self.compat)
        config["version"] = stable
        compat["add_on"]["version"] = stable
        with self.assertRaisesRegex(validate.ValidationError, "FTW_BUNDLE_VERSION"):
            validate.validate_common(config, compat)


class PilotRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")
        self.version = str(self.compat["add_on"]["version"])
        self.record = validate.load_yaml(validate.ROOT / f"pilot/{self.version}.yaml")

    def test_candidate_and_blocked_checks_pass(self) -> None:
        validate.validate_pilot(self.version, self.compat)

    def test_driver_commit_mismatch_fails(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["drivers"]["tested_baseline"]["commit"] = "f" * 40
        with self.assertRaisesRegex(validate.ValidationError, "pilot driver commit differs"):
            validate.validate_pilot(self.version, compat)

    def test_passed_check_needs_evidence(self) -> None:
        record = copy.deepcopy(self.record)
        record["checks"]["install"]["status"] = "passed"
        with self.assertRaisesRegex(validate.ValidationError, "lacks evidence"):
            self._validate_record(record)

    def test_passed_gate_needs_passed_record(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["qualification"]["home_assistant_os_supervisor"] = {
            "status": "passed",
            "evidence": "https://example.com/pilot",
            "record": f"pilot/{self.version}.yaml",
        }
        with self.assertRaisesRegex(validate.ValidationError, "needs a passed pilot record"):
            validate.validate_pilot(self.version, compat)

    def test_passed_update_needs_prior_beta_coordinates(self) -> None:
        record = copy.deepcopy(self.record)
        record["checks"]["update"]["status"] = "passed"
        record["checks"]["update"]["evidence"] = "https://example.com/update"
        with self.assertRaisesRegex(validate.ValidationError, "prior beta version"):
            self._validate_record(record)

    def test_passed_rollback_needs_backup_reference(self) -> None:
        record = copy.deepcopy(self.record)
        record["checks"]["rollback"]["status"] = "passed"
        record["checks"]["rollback"]["evidence"] = "https://example.com/rollback"
        with self.assertRaisesRegex(validate.ValidationError, "backup reference"):
            self._validate_record(record)

    def _validate_record(self, record: dict) -> None:
        original = validate.load_yaml
        with mock.patch.object(
            validate,
            "load_yaml",
            side_effect=lambda path: record if path.name == f"{self.version}.yaml" else original(path),
        ):
            validate.validate_pilot(self.version, self.compat)


class StablePilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")
        self.beta_version = str(self.compat["add_on"]["version"])
        self.stable_version = self.beta_version.split("-beta.", 1)[0]
        self.record = validate.load_yaml(validate.ROOT / f"pilot/{self.beta_version}.yaml")
        self.compat["add_on"].update(
            version=self.stable_version,
            channel="stable",
            manifest_digest=APP_DIGEST,
        )
        self.compat["qualification"]["home_assistant_os_supervisor"] = {
            "status": "passed",
            "evidence": "https://example.com/ha-pilot",
            "record": f"pilot/{self.beta_version}.yaml",
        }
        self.compat["qualification"]["promoted_from_beta"] = {
            "channel": "beta",
            "version": self.beta_version,
            "manifest_digest": APP_DIGEST,
            "source_commit": SOURCE_COMMIT,
        }
        self.record["status"] = "passed"
        self.record["candidate"]["source_commit"] = SOURCE_COMMIT
        self.record["candidate"]["manifest_digest"] = APP_DIGEST
        for name, check in self.record["checks"].items():
            check["status"] = "passed"
            check["evidence"] = f"https://example.com/{name}"
        self.record["checks"]["update"].update(
            from_version="0.0.9-beta.2",
            from_manifest_digest=PRIOR_DIGEST,
            to_manifest_digest=APP_DIGEST,
        )
        self.record["checks"]["rollback"].update(
            from_manifest_digest=APP_DIGEST,
            to_version="0.0.9-beta.2",
            to_manifest_digest=PRIOR_DIGEST,
            backup_reference="https://example.com/backup",
        )

    def validate(self) -> None:
        original = validate.load_yaml
        with mock.patch.object(
            validate,
            "load_yaml",
            side_effect=lambda path: self.record if path.name == f"{self.beta_version}.yaml" else original(path),
        ):
            validate.validate_channel("stable", {"version": self.stable_version}, self.compat)

    def test_exact_passed_beta_pilot_allows_stable(self) -> None:
        self.validate()

    def test_blocked_record_fails_stable(self) -> None:
        self.record["status"] = "blocked"
        with self.assertRaisesRegex(validate.ValidationError, "needs a passed pilot record"):
            self.validate()

    def test_wrong_source_commit_fails_stable(self) -> None:
        self.record["candidate"]["source_commit"] = "f" * 40
        with self.assertRaisesRegex(validate.ValidationError, "source commit differs from beta"):
            self.validate()

    def test_wrong_manifest_digest_fails_stable(self) -> None:
        wrong = "sha256:" + "f" * 64
        self.record["candidate"]["manifest_digest"] = wrong
        self.record["checks"]["update"]["to_manifest_digest"] = wrong
        self.record["checks"]["rollback"]["from_manifest_digest"] = wrong
        with self.assertRaisesRegex(validate.ValidationError, "digest differs from beta"):
            self.validate()

    def test_blocked_check_fails_stable(self) -> None:
        self.record["checks"]["optimizer_recovery"]["status"] = "blocked"
        with self.assertRaisesRegex(validate.ValidationError, "passed pilot has blocked checks"):
            self.validate()

    def test_candidate_core_mismatch_fails_stable(self) -> None:
        self.record["candidate"]["core"]["digest"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(validate.ValidationError, "pilot core digest differs"):
            self.validate()


class DriverBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")

    def test_release_values_accept_baseline(self) -> None:
        validate.require_release_values(self.compat, require_app_digest=False)

    def test_manifest_sha256_must_be_raw_hex(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["drivers"]["tested_baseline"]["manifest_sha256"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(validate.ValidationError, "manifest SHA-256 is invalid"):
            validate.require_release_values(compat, require_app_digest=False)


if __name__ == "__main__":
    unittest.main()
