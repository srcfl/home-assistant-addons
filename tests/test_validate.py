from __future__ import annotations

import copy
import unittest
from unittest import mock

from scripts import validate


class PilotRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")
        self.record = validate.load_yaml(validate.ROOT / "pilot/0.1.0-beta.1.yaml")

    def test_candidate_and_blocked_checks_pass(self) -> None:
        validate.validate_beta_pilot("0.1.0-beta.1", self.compat)

    def test_driver_commit_mismatch_fails(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["drivers"]["tested_baseline"]["commit"] = "f" * 40
        with self.assertRaisesRegex(validate.ValidationError, "pilot driver commit differs"):
            validate.validate_beta_pilot("0.1.0-beta.1", compat)

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
            validate.validate_beta_pilot("0.1.0-beta.1", compat)

    def _validate_record(self, record: dict) -> None:
        original = validate.load_yaml
        with mock.patch.object(
            validate,
            "load_yaml",
            side_effect=lambda path: record if path.name == "0.1.0-beta.1.yaml" else original(path),
        ):
            validate.validate_beta_pilot("0.1.0-beta.1", self.compat)


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
