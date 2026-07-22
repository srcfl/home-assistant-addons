from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.error import URLError

from scripts import release_gate


FIXTURES = pathlib.Path(__file__).parent / "fixtures/release"
DIGEST = "sha256:" + "d" * 64
COMMIT = "e" * 40
DRIVER_COMMIT = "a" * 40
DRIVER_KEY_ID = "ftw-test-1"
DRIVER_PUBLIC_KEY = "iojj3XQJ8ZX9UtstPLpdcspnCb8dlBIb83SIAbQPb1w="
DRIVER_SHA256 = "f62bd732896aeee3b36286d8b230fcb2d798a8d6244b4b4fe7b43bce68034099"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def raw_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


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


class BetaResumeTargetTests(unittest.TestCase):
    def validate(self, **overrides: object) -> None:
        values = {
            "git_tag_exists": False,
            "release_exists": False,
            "version_digest": DIGEST,
            "beta_digest": DIGEST,
            "expected_digest": DIGEST,
        }
        values.update(overrides)
        release_gate.validate_beta_resume_target_state(**values)

    def test_exact_partial_target_passes(self) -> None:
        self.validate()

    def test_existing_git_tag_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "Git tag"):
            self.validate(git_tag_exists=True)

    def test_existing_release_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "GitHub release"):
            self.validate(release_exists=True)

    def test_missing_version_tag_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "version tag is missing"):
            self.validate(version_digest=None)

    def test_version_digest_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "version tag digest"):
            self.validate(version_digest="sha256:" + "a" * 64)

    def test_missing_beta_alias_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "beta alias is missing"):
            self.validate(beta_digest=None)

    def test_beta_alias_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "beta alias digest"):
            self.validate(beta_digest="sha256:" + "a" * 64)

class WorkflowSourceTests(unittest.TestCase):
    def test_main_at_expected_commit_passes(self) -> None:
        release_gate.validate_workflow_source(
            ref="refs/heads/main", expected_sha=COMMIT, actual_sha=COMMIT
        )

    def test_non_main_branch_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "refs/heads/main"):
            release_gate.validate_workflow_source(
                ref="refs/heads/agent/release", expected_sha=COMMIT, actual_sha=COMMIT
            )

    def test_wrong_checkout_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "checked-out HEAD"):
            release_gate.validate_workflow_source(
                ref="refs/heads/main", expected_sha=COMMIT, actual_sha="f" * 40
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


class ResumeRunTests(unittest.TestCase):
    def setUp(self) -> None:
        value = fixture("resume-run.json")
        self.run_record = value["run"]
        self.jobs = value["jobs"]

    def validate(self) -> None:
        release_gate.validate_resume_run(
            run_record=self.run_record,
            jobs=self.jobs,
            requested_version="0.1.0-beta.1",
            expected_version="0.1.0-beta.1",
            expected_source_commit=COMMIT,
        )

    def test_exact_failed_publish_run_passes(self) -> None:
        self.validate()

    def test_each_run_binding_mismatch_fails(self) -> None:
        changes = {
            "status": "in_progress",
            "conclusion": "success",
            "event": "push",
            "head_branch": "agent/feature",
            "head_sha": "f" * 40,
            "path": ".github/workflows/check.yml",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                record = copy.deepcopy(self.run_record)
                record[field] = value
                with self.assertRaises(release_gate.GateError):
                    release_gate.validate_resume_run(
                        run_record=record,
                        jobs=self.jobs,
                        requested_version="0.1.0-beta.1",
                        expected_version="0.1.0-beta.1",
                        expected_source_commit=COMMIT,
                    )

    def test_version_input_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "version input"):
            release_gate.validate_resume_run(
                run_record=self.run_record,
                jobs=self.jobs,
                requested_version="0.1.0-beta.2",
                expected_version="0.1.0-beta.1",
                expected_source_commit=COMMIT,
            )

    def test_prepare_log_binds_exact_input(self) -> None:
        log = "step output REQUESTED_VERSION: 0.1.0-beta.1\n"
        self.assertEqual(release_gate.requested_version_from_log(log), "0.1.0-beta.1")

    def test_missing_or_ambiguous_prepare_input_fails(self) -> None:
        for log in (
            "no input here",
            "REQUESTED_VERSION: 0.1.0-beta.1\nREQUESTED_VERSION: 0.1.0-beta.2\n",
        ):
            with self.subTest(log=log):
                with self.assertRaisesRegex(release_gate.GateError, "missing or ambiguous"):
                    release_gate.requested_version_from_log(log)

    def test_missing_required_job_fails(self) -> None:
        self.jobs.pop()
        with self.assertRaisesRegex(release_gate.GateError, "Record digest"):
            self.validate()

    def test_each_job_conclusion_mismatch_fails(self) -> None:
        for index, job in enumerate(self.jobs):
            with self.subTest(job=job["name"]):
                jobs = copy.deepcopy(self.jobs)
                jobs[index]["conclusion"] = "failure" if job["conclusion"] == "success" else "success"
                with self.assertRaisesRegex(release_gate.GateError, "conclusion mismatch"):
                    release_gate.validate_resume_run(
                        run_record=self.run_record,
                        jobs=jobs,
                        requested_version="0.1.0-beta.1",
                        expected_version="0.1.0-beta.1",
                        expected_source_commit=COMMIT,
                    )


class AddOnImageEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = fixture("addon-index.json")
        labels = {
            "io.hass.version": "0.1.0-beta.1",
            "org.opencontainers.image.version": "0.1.0-beta.1",
            "org.opencontainers.image.revision": "e" * 40,
            "com.sourceful.ftw.core.version": "v1.10.0-beta.1",
            "com.sourceful.ftw.core.digest": "sha256:" + "a" * 64,
            "com.sourceful.ftw.optimizer.version": "v1.3.2-beta.1",
            "com.sourceful.ftw.optimizer.digest": "sha256:" + "b" * 64,
            "com.sourceful.ftw.update-owner": "home_assistant_supervisor",
        }
        self.images = {
            "amd64": {"config": {"Labels": {**labels, "io.hass.arch": "amd64"}}},
            "arm64": {"config": {"Labels": {**labels, "io.hass.arch": "aarch64"}}},
        }
        self.compatibility = {
            "core": {"version": "v1.10.0-beta.1", "digest": "sha256:" + "a" * 64},
            "optimizer": {"version": "v1.3.2-beta.1", "digest": "sha256:" + "b" * 64},
        }

    def validate(self) -> dict[str, str]:
        return release_gate.validate_add_on_platforms(
            index=self.index,
            platform_images=self.images,
            expected_version="0.1.0-beta.1",
            expected_commit="e" * 40,
            compatibility=self.compatibility,
        )

    def test_exact_architectures_and_labels_pass(self) -> None:
        self.assertEqual(
            self.validate(),
            {
                "amd64": "sha256:" + "1" * 64,
                "aarch64": "sha256:" + "2" * 64,
            },
        )

    def test_missing_architecture_fails(self) -> None:
        self.index["manifests"].pop(1)
        with self.assertRaisesRegex(release_gate.GateError, "required Linux architectures"):
            self.validate()

    def test_extra_architecture_fails(self) -> None:
        self.index["manifests"].append(
            {"digest": "sha256:" + "9" * 64, "platform": {"architecture": "s390x", "os": "linux"}}
        )
        with self.assertRaisesRegex(release_gate.GateError, "unsupported Linux architectures"):
            self.validate()

    def test_each_release_label_mismatch_fails(self) -> None:
        for key in tuple(self.images["amd64"]["config"]["Labels"]):
            with self.subTest(label=key):
                images = copy.deepcopy(self.images)
                images["amd64"]["config"]["Labels"][key] = "wrong"
                with self.assertRaisesRegex(release_gate.GateError, "label"):
                    release_gate.validate_add_on_platforms(
                        index=self.index,
                        platform_images=images,
                        expected_version="0.1.0-beta.1",
                        expected_commit="e" * 40,
                        compatibility=self.compatibility,
                    )

    def test_attestation_descriptors_are_required(self) -> None:
        self.assertEqual(len(release_gate.attestation_descriptor_digests(self.index, "fixture")), 2)
        self.index["manifests"] = self.index["manifests"][:2]
        with self.assertRaisesRegex(release_gate.GateError, "lacks build attestation"):
            release_gate.attestation_descriptor_digests(self.index, "fixture")

    def test_per_arch_source_indexes_match_final_descriptors(self) -> None:
        final = release_gate.runtime_descriptors(self.index, "final")
        final_attestations = release_gate.attestation_descriptor_digests(self.index, "final")
        cases = (
            ("amd64", fixture("addon-amd64-index.json")),
            ("arm64", fixture("addon-aarch64-index.json")),
        )
        for architecture, source in cases:
            with self.subTest(architecture=architecture):
                release_gate.validate_source_index_link(
                    source_index=source,
                    name="source",
                    architecture=architecture,
                    expected_runtime_digest=final[architecture]["digest"],
                    final_attestations=final_attestations,
                )

    def test_source_runtime_digest_mismatch_is_detectable(self) -> None:
        source = fixture("addon-amd64-index.json")
        source["manifests"][0]["digest"] = "sha256:" + "9" * 64
        final = release_gate.runtime_descriptors(self.index, "final")
        with self.assertRaisesRegex(release_gate.GateError, "does not match final index"):
            release_gate.validate_source_index_link(
                source_index=source,
                name="source",
                architecture="amd64",
                expected_runtime_digest=final["amd64"]["digest"],
                final_attestations=release_gate.attestation_descriptor_digests(self.index, "final"),
            )


class SbomEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verification = fixture("sbom-attestation.json")
        self.digest = "sha256:" + "5" * 64
        self.image = "ghcr.io/srcfl/home-assistant-addons/amd64-ftw"

    def predicate(self, verification: object | None = None) -> dict:
        return release_gate.verified_sbom_predicate(
            self.verification if verification is None else verification,
            expected_name=self.image,
            expected_digest=self.digest,
        )

    def test_exact_signed_sbom_passes(self) -> None:
        self.assertEqual(self.predicate(), fixture("sbom.json"))

    def test_api_and_oci_use_separate_workflow_identities(self) -> None:
        api = release_gate.attestation_verify_command(
            image=self.image,
            digest=self.digest,
            repository="srcfl/home-assistant-addons",
            source_commit=COMMIT,
        )
        oci = release_gate.attestation_verify_command(
            image=self.image,
            digest=self.digest,
            repository="srcfl/home-assistant-addons",
            source_commit="f" * 40,
            cert_identity=release_gate.FINALIZE_WORKFLOW_IDENTITY,
            from_oci=True,
        )
        self.assertIn(release_gate.RELEASE_WORKFLOW_IDENTITY, api)
        self.assertIn(COMMIT, api)
        self.assertIn(release_gate.FINALIZE_WORKFLOW_IDENTITY, oci)
        self.assertIn("f" * 40, oci)
        self.assertIn("--bundle-from-oci", oci)

    def test_wrong_predicate_type_fails(self) -> None:
        value = copy.deepcopy(self.verification)
        value[0]["verificationResult"]["statement"]["predicateType"] = "wrong"
        with self.assertRaisesRegex(release_gate.GateError, "predicate type"):
            self.predicate(value)

    def test_wrong_subject_fails(self) -> None:
        value = copy.deepcopy(self.verification)
        value[0]["verificationResult"]["statement"]["subject"][0]["name"] = "wrong"
        with self.assertRaisesRegex(release_gate.GateError, "subject name"):
            self.predicate(value)

    def test_wrong_digest_fails(self) -> None:
        value = copy.deepcopy(self.verification)
        value[0]["verificationResult"]["statement"]["subject"][0]["digest"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(release_gate.GateError, "digest mismatch"):
            self.predicate(value)

    def test_disagreeing_attestations_fail(self) -> None:
        value = copy.deepcopy(self.verification)
        value.append(copy.deepcopy(value[0]))
        value[1]["verificationResult"]["statement"]["predicate"]["name"] = "other"
        with self.assertRaisesRegex(release_gate.GateError, "disagree"):
            self.predicate(value)

    def test_sbom_artifact_must_match_signed_predicate(self) -> None:
        release_gate.validate_sbom_artifact(FIXTURES / "sbom.json", self.predicate(), "amd64")
        wrong = self.predicate()
        wrong["name"] = "wrong"
        with self.assertRaisesRegex(release_gate.GateError, "differs"):
            release_gate.validate_sbom_artifact(FIXTURES / "sbom.json", wrong, "amd64")

    def test_exact_missing_oci_message_can_be_resumed(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Error: no attestations found in the OCI registry"
        )
        with mock.patch.object(release_gate, "run", return_value=result):
            self.assertFalse(
                release_gate.verify_sbom_from_oci(
                    image=self.image,
                    digest=self.digest,
                    repository="srcfl/home-assistant-addons",
                    attestation_source_commit=COMMIT,
                    cert_identity=release_gate.FINALIZE_WORKFLOW_IDENTITY,
                    expected_predicate=self.predicate(),
                    allow_missing=True,
                )
            )

    def test_other_oci_error_fails_closed(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="network failed")
        with mock.patch.object(release_gate, "run", return_value=result):
            with self.assertRaisesRegex(release_gate.GateError, "network failed"):
                release_gate.verify_sbom_from_oci(
                    image=self.image,
                    digest=self.digest,
                    repository="srcfl/home-assistant-addons",
                    attestation_source_commit=COMMIT,
                    cert_identity=release_gate.FINALIZE_WORKFLOW_IDENTITY,
                    expected_predicate=self.predicate(),
                    allow_missing=True,
                )


class BetaManifestTests(unittest.TestCase):
    def test_resume_manifest_keeps_original_source_and_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "release-manifest.json"
            release_gate.write_beta_release_manifest(
                path=path,
                version="0.1.0-beta.1",
                digest=DIGEST,
                source_commit=COMMIT,
            )
            manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_commit"], COMMIT)
        self.assertEqual(manifest["manifest_digest"], DIGEST)
        self.assertEqual(manifest["core"]["version"], "v1.10.0-beta.1")
        self.assertEqual(manifest["optimizer"]["version"], "v1.3.2-beta.1")
        self.assertNotIn("updater", manifest)

class DriverManifestTests(unittest.TestCase):
    def validate(self, raw: bytes, *, sha256: str = DRIVER_SHA256) -> dict:
        return release_gate.validate_signed_driver_manifest(
            raw,
            expected_sha256=sha256,
            expected_commit=DRIVER_COMMIT,
            expected_key_id=DRIVER_KEY_ID,
            public_key_base64=DRIVER_PUBLIC_KEY,
        )

    def test_exact_hash_signature_and_source_commit_pass(self) -> None:
        payload = self.validate(raw_fixture("driver-manifest.json"))
        self.assertEqual(payload["commit"], DRIVER_COMMIT)

    def test_raw_hash_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "SHA-256 mismatch"):
            self.validate(raw_fixture("driver-manifest.json"), sha256="f" * 64)

    def test_signature_mismatch_fails(self) -> None:
        envelope = fixture("driver-manifest.json")
        envelope["signature"] = "A" * 88
        raw = release_gate.canonical_json(envelope) + b"\n"
        with self.assertRaisesRegex(release_gate.GateError, "signature verification failed"):
            self.validate(raw, sha256=hashlib.sha256(raw).hexdigest())

    def test_payload_commit_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(release_gate.GateError, "payload commit mismatch"):
            release_gate.validate_signed_driver_manifest(
                raw_fixture("driver-manifest.json"),
                expected_sha256=DRIVER_SHA256,
                expected_commit="b" * 40,
                expected_key_id=DRIVER_KEY_ID,
                public_key_base64=DRIVER_PUBLIC_KEY,
            )

    def test_driver_source_commit_mismatch_fails(self) -> None:
        raw = raw_fixture("driver-manifest-wrong-source.json")
        with self.assertRaisesRegex(release_gate.GateError, "driver source commit mismatch"):
            self.validate(raw, sha256=hashlib.sha256(raw).hexdigest())

    def test_network_error_fails_closed(self) -> None:
        with mock.patch.object(release_gate, "urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(release_gate.GateError, "could not download"):
                release_gate.download_driver_manifest("https://example.com/manifest.json")


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
