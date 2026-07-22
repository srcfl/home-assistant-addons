from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FINALIZE = (ROOT / ".github/workflows/finalize-beta.yml").read_text(encoding="utf-8")
PUBLISH = (ROOT / ".github/workflows/release-beta.yml").read_text(encoding="utf-8")


class FinalizeWorkflowTests(unittest.TestCase):
    def test_both_beta_workflows_share_global_concurrency(self) -> None:
        marker = "group: ftw-beta-publication"
        self.assertIn(marker, FINALIZE)
        self.assertIn(marker, PUBLISH)
        self.assertNotIn("ftw-beta-${{ inputs.version }}", PUBLISH)

    def test_finalize_requires_exact_resume_coordinates(self) -> None:
        for name in ("version", "manifest_digest", "source_commit", "source_run_id"):
            self.assertRegex(FINALIZE, rf"(?m)^      {name}:$")

    def test_finalize_cannot_build_push_or_retag_images(self) -> None:
        forbidden = (
            "build-image",
            "publish-multi-arch-manifest",
            "docker buildx imagetools create",
            "docker tag",
            "docker push",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, FINALIZE)

    def test_only_registry_writer_is_one_index_attestation(self) -> None:
        self.assertEqual(FINALIZE.count("uses: actions/attest@v4"), 1)
        self.assertEqual(FINALIZE.count("push-to-registry: true"), 1)
        self.assertIn("subject-digest: ${{ inputs.manifest_digest }}", FINALIZE)

    def test_all_preflight_steps_precede_login_and_write(self) -> None:
        login = FINALIZE.index("name: Log in for the index attestation")
        attest = FINALIZE.index("uses: actions/attest@v4")
        for marker in (
            "name: Verify the failed run and immutable images",
            "name: Download the original platform SBOMs",
            "name: Verify the amd64 source index signature",
            "name: Verify the aarch64 source index signature",
            "name: Verify the multi-arch index signature",
            "name: Verify GitHub attestations and original SBOMs",
            "name: Create the exact release manifest",
            "name: Double-check immutable targets",
        ):
            with self.subTest(marker=marker):
                self.assertLess(FINALIZE.index(marker), login)
        self.assertLess(login, attest)

    def test_release_waits_for_oci_verification(self) -> None:
        attest = FINALIZE.index("uses: actions/attest@v4")
        verify = FINALIZE.index("name: Verify the index SBOM from OCI")
        release = FINALIZE.index("name: Create the beta release at the original source commit")
        self.assertLess(attest, verify)
        self.assertLess(verify, release)
        self.assertIn('--target "${SOURCE_COMMIT}"', FINALIZE)
        self.assertIn("FINALIZER_COMMIT: ${{ github.sha }}", FINALIZE)
        self.assertIn('--finalizer-commit "${FINALIZER_COMMIT}"', FINALIZE)

    def test_finalize_has_no_stable_operation(self) -> None:
        for value in ("promote-stable", "${IMAGE}:stable", "--latest=true"):
            self.assertNotIn(value, FINALIZE)


class PublishWorkflowRegressionTests(unittest.TestCase):
    def test_evidence_job_logs_in_before_final_attestation(self) -> None:
        login = PUBLISH.rfind("uses: docker/login-action@v4")
        attest = PUBLISH.rfind("uses: actions/attest@v4")
        self.assertGreater(login, 0)
        self.assertGreater(attest, login)


if __name__ == "__main__":
    unittest.main()
