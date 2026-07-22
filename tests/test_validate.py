from __future__ import annotations

import copy
import unittest
from unittest import mock

from scripts import validate


APP_DIGEST = "sha256:" + "d" * 64
PRIOR_DIGEST = "sha256:" + "c" * 64
SOURCE_COMMIT = "e" * 40


class PilotRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")
        self.record = validate.load_yaml(validate.ROOT / "pilot/0.1.0-beta.1.yaml")

    def test_candidate_and_blocked_checks_pass(self) -> None:
        validate.validate_pilot("0.1.0-beta.1", self.compat)

    def test_driver_commit_mismatch_fails(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["drivers"]["tested_baseline"]["commit"] = "f" * 40
        with self.assertRaisesRegex(validate.ValidationError, "pilot driver commit differs"):
            validate.validate_pilot("0.1.0-beta.1", compat)

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
            "record": "pilot/0.1.0-beta.1.yaml",
        }
        with self.assertRaisesRegex(validate.ValidationError, "needs a passed pilot record"):
            validate.validate_pilot("0.1.0-beta.1", compat)

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
            side_effect=lambda path: record if path.name == "0.1.0-beta.1.yaml" else original(path),
        ):
            validate.validate_pilot("0.1.0-beta.1", self.compat)


class StablePilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")
        self.record = validate.load_yaml(validate.ROOT / "pilot/0.1.0-beta.1.yaml")
        self.compat["add_on"].update(
            version="0.1.0",
            channel="stable",
            manifest_digest=APP_DIGEST,
        )
        self.compat["qualification"]["home_assistant_os_supervisor"] = {
            "status": "passed",
            "evidence": "https://example.com/ha-pilot",
            "record": "pilot/0.1.0-beta.1.yaml",
        }
        self.compat["qualification"]["promoted_from_beta"] = {
            "channel": "beta",
            "version": "0.1.0-beta.1",
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
            side_effect=lambda path: self.record if path.name == "0.1.0-beta.1.yaml" else original(path),
        ):
            validate.validate_channel("stable", {"version": "0.1.0"}, self.compat)

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
