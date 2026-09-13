from __future__ import annotations

import copy
import unittest

import yaml

from scripts import upstream_sync, validate


CORE_DIGEST = "sha256:" + "a" * 64
CORE_COMMIT = "b" * 40
ADD_ON_DIGEST = "sha256:" + "d" * 64
ADD_ON_COMMIT = "e" * 40


def load_repository() -> tuple[dict, dict, str]:
    compat = validate.load_yaml(validate.ROOT / "compatibility.yaml")
    beta_text = (validate.ROOT / "ftw-beta/config.yaml").read_text(encoding="utf-8")
    return compat, yaml.safe_load(beta_text), beta_text


def promoted(compat: dict, *, version: str = "3.4.2", beta: str = "3.4.2-beta.4") -> dict:
    compat = copy.deepcopy(compat)
    compat["stable"] = {
        "add_on": "ftw",
        "version": version,
        "promoted_from_beta": beta,
        "manifest_digest": ADD_ON_DIGEST,
        "source_commit": ADD_ON_COMMIT,
        "core": {
            "version": f"v{version}",
            "commit": CORE_COMMIT,
            "digest": CORE_DIGEST,
            "release": f"https://github.com/srcfl/ftw/releases/tag/v{version}",
        },
    }
    compat["qualification"]["home_assistant_os_supervisor"].update(
        status="passed",
        add_on_version=beta,
        evidence="https://github.com/srcfl/home-assistant-addons/issues/1",
    )
    return compat


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = (validate.ROOT / "ftw/Dockerfile").read_text(encoding="utf-8")

    def test_repository_layout_passes(self) -> None:
        validate.validate_repository()

    def test_dockerfile_binds_the_image_tag_to_the_core_version(self) -> None:
        validate.validate_core_image_tag_contract(self.dockerfile)
        for version in ("v3.4.2-beta.4", "v3.4.2"):
            with self.subTest(version=version):
                rendered = self.dockerfile.replace("${CORE_VERSION}", version)
                self.assertIn(f"FTW_IMAGE_TAG={version}", rendered)

    def test_app_version_cannot_replace_the_core_version(self) -> None:
        dockerfile = self.dockerfile.replace(
            "FTW_IMAGE_TAG=${CORE_VERSION}",
            "FTW_IMAGE_TAG=${BUILD_VERSION}",
        )
        with self.assertRaisesRegex(validate.ValidationError, "must set FTW_IMAGE_TAG from CORE_VERSION"):
            validate.validate_core_image_tag_contract(dockerfile)

    def test_dockerfile_builds_from_core_alone(self) -> None:
        self.assertIn("FROM ${FTW_CORE_FROM}", self.dockerfile)
        self.assertNotIn("optimizer", self.dockerfile.lower())
        self.assertNotIn("apt-get", self.dockerfile)


class BetaChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat, self.config, _ = load_repository()

    def validate(self, config: dict | None = None, compat: dict | None = None) -> None:
        compat = self.compat if compat is None else compat
        validate.validate_common(compat)
        validate.validate_beta(compat)
        validate.validate_add_on_config(self.config if config is None else config, compat, "beta")

    def test_current_pins_pass(self) -> None:
        self.validate()

    def test_validate_all_reports_beta_only_before_promotion(self) -> None:
        self.assertEqual(validate.validate_all(self.compat), ["beta"])

    def test_app_version_must_mirror_the_core_version(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["beta"]["version"] = "9.9.9-beta.1"
        with self.assertRaisesRegex(validate.ValidationError, "mirror the Core version"):
            self.validate(compat=compat)

    def test_beta_core_pin_must_be_a_prerelease(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["beta"]["version"] = "3.4.2"
        compat["beta"]["core"]["version"] = "v3.4.2"
        compat["beta"]["core"]["release"] = "https://github.com/srcfl/ftw/releases/tag/v3.4.2"
        with self.assertRaisesRegex(validate.ValidationError, "prerelease"):
            self.validate(compat=compat)

    def test_bundle_version_must_match_the_app_version(self) -> None:
        config = copy.deepcopy(self.config)
        config["environment"]["FTW_BUNDLE_VERSION"] = "0.0.0-beta.1"
        with self.assertRaisesRegex(validate.ValidationError, "FTW_BUNDLE_VERSION"):
            self.validate(config=config)

    def test_image_tag_must_be_the_pinned_core_release(self) -> None:
        config = copy.deepcopy(self.config)
        config["environment"]["FTW_IMAGE_TAG"] = "v0.0.0-beta.1"
        with self.assertRaisesRegex(validate.ValidationError, "FTW_IMAGE_TAG"):
            self.validate(config=config)

    def test_supervisor_init_stays_at_its_default(self) -> None:
        config = copy.deepcopy(self.config)
        config["init"] = False
        with self.assertRaisesRegex(validate.ValidationError, "init"):
            self.validate(config=config)

    def test_beta_app_is_experimental(self) -> None:
        config = copy.deepcopy(self.config)
        del config["stage"]
        with self.assertRaisesRegex(validate.ValidationError, "stage"):
            self.validate(config=config)

    def test_self_update_stays_off(self) -> None:
        config = copy.deepcopy(self.config)
        config["environment"]["FTW_SELFUPDATE_ENABLED"] = "1"
        with self.assertRaisesRegex(validate.ValidationError, "self-update"):
            self.validate(config=config)


class StableChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat, _, self.beta_text = load_repository()

    def test_unpromoted_stable_is_all_null(self) -> None:
        validate.validate_stable(self.compat, required=False)
        with self.assertRaisesRegex(validate.ValidationError, "no promoted version"):
            validate.validate_stable(self.compat, required=True)

    def test_partial_stable_record_fails(self) -> None:
        compat = copy.deepcopy(self.compat)
        compat["stable"]["manifest_digest"] = ADD_ON_DIGEST
        with self.assertRaisesRegex(validate.ValidationError, "must be null"):
            validate.validate_stable(compat, required=False)

    def test_promoted_stable_passes(self) -> None:
        compat = promoted(self.compat)
        validate.validate_common(compat)
        validate.validate_stable(compat, required=True)

    def test_promotion_requires_a_passed_pilot(self) -> None:
        compat = promoted(self.compat)
        compat["qualification"]["home_assistant_os_supervisor"]["status"] = "blocked"
        with self.assertRaisesRegex(validate.ValidationError, "pilot"):
            validate.validate_stable(compat, required=True)

    def test_promoted_beta_must_share_the_stable_base(self) -> None:
        compat = promoted(self.compat, beta="3.4.1-beta.2")
        with self.assertRaisesRegex(validate.ValidationError, "differ"):
            validate.validate_stable(compat, required=True)

    def test_stable_core_pin_must_not_be_a_prerelease(self) -> None:
        compat = promoted(self.compat)
        compat["stable"]["core"]["version"] = "v3.4.2-beta.4"
        compat["stable"]["core"]["release"] = "https://github.com/srcfl/ftw/releases/tag/v3.4.2-beta.4"
        with self.assertRaisesRegex(validate.ValidationError, "prerelease"):
            validate.validate_stable(compat, required=True)

    def test_rendered_stable_config_passes(self) -> None:
        compat = promoted(self.compat)
        config = yaml.safe_load(upstream_sync.render_stable_config(self.beta_text, "3.4.2", "v3.4.2"))
        validate.validate_add_on_config(config, compat, "stable")
        self.assertEqual(config["slug"], "ftw")
        self.assertNotIn("stage", config)

    def test_stable_config_must_not_carry_the_experimental_stage(self) -> None:
        compat = promoted(self.compat)
        config = yaml.safe_load(upstream_sync.render_stable_config(self.beta_text, "3.4.2", "v3.4.2"))
        config["stage"] = "experimental"
        with self.assertRaisesRegex(validate.ValidationError, "stable stage"):
            validate.validate_add_on_config(config, compat, "stable")


class QualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat, _, _ = load_repository()

    def pilot(self) -> dict:
        return self.compat["qualification"]["home_assistant_os_supervisor"]

    def test_passed_pilot_needs_public_evidence(self) -> None:
        self.pilot().update(status="passed", add_on_version="3.4.2-beta.4", evidence=None)
        with self.assertRaisesRegex(validate.ValidationError, "evidence"):
            validate.validate_common(self.compat)

    def test_passed_pilot_names_the_beta_it_ran_on(self) -> None:
        self.pilot().update(status="passed", add_on_version=None, evidence="https://example.com/pilot")
        with self.assertRaisesRegex(validate.ValidationError, "beta app version"):
            validate.validate_common(self.compat)

    def test_checklist_path_is_fixed(self) -> None:
        self.pilot()["checklist"] = "pilot/other.md"
        with self.assertRaisesRegex(validate.ValidationError, "checklist"):
            validate.validate_common(self.compat)

    def test_unknown_status_fails(self) -> None:
        self.pilot()["status"] = "pending"
        with self.assertRaisesRegex(validate.ValidationError, "status is invalid"):
            validate.validate_common(self.compat)


class DriverBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compat, _, _ = load_repository()

    def test_current_baseline_passes(self) -> None:
        validate.validate_common(self.compat)

    def test_manifest_sha256_must_be_raw_hex(self) -> None:
        self.compat["drivers"]["tested_baseline"]["manifest_sha256"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(validate.ValidationError, "manifest SHA-256 is invalid"):
            validate.validate_common(self.compat)


if __name__ == "__main__":
    unittest.main()
