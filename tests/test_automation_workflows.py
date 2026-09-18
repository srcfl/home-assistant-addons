from __future__ import annotations

import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
SYNC = (ROOT / ".github/workflows/sync-upstream.yml").read_text(encoding="utf-8")
AUTO_PUBLISH = (ROOT / ".github/workflows/auto-publish.yml").read_text(encoding="utf-8")


class WorkflowSyntaxTests(unittest.TestCase):
    """GitHub refuses a workflow file it cannot parse. The failed run has no jobs
    and no log, and the hourly sync and the ftw-release dispatch both stop. The
    other tests here read the files as text, so parse each one first."""

    def test_every_workflow_file_is_valid_yaml(self) -> None:
        workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertTrue(workflows)
        for path in workflows:
            with self.subTest(workflow=path.name):
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(document, dict)
                self.assertIn("jobs", document)


class SyncWorkflowTests(unittest.TestCase):
    def test_sync_watches_upstream_releases_and_the_clock(self) -> None:
        self.assertIn("repository_dispatch:", SYNC)
        self.assertIn("types: [ftw-release]", SYNC)
        self.assertIn("schedule:", SYNC)

    def test_sync_serializes_its_runs(self) -> None:
        self.assertIn("group: ftw-upstream-sync", SYNC)
        self.assertIn("cancel-in-progress: false", SYNC)

    def test_sync_follows_the_check_run_it_dispatched(self) -> None:
        # GitHub also opens a pull_request run for the bot's PR and holds it
        # for maintainer approval. Following that one never finishes.
        self.assertIn("gh workflow run check.yml --ref", SYNC)
        self.assertIn('--branch "${BRANCH}" --event workflow_dispatch', SYNC)

    def test_sync_only_runs_in_the_canonical_repository(self) -> None:
        self.assertIn("if: github.repository == 'srcfl/home-assistant-addons'", SYNC)

    def test_sync_cannot_write_packages(self) -> None:
        self.assertNotIn("packages: write", SYNC)
        self.assertIn("packages: read", SYNC)

    def test_sync_cannot_build_push_or_retag_images(self) -> None:
        forbidden = (
            "build-image",
            "publish-multi-arch-manifest",
            "docker buildx imagetools create",
            "docker tag",
            "docker push",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, SYNC)

    def test_sync_validates_and_tests_before_opening_the_pr(self) -> None:
        resolve = SYNC.index("name: Resolve and apply upstream pins")
        validate = SYNC.index("python scripts/validate.py")
        tests = SYNC.index("python -m unittest discover")
        pr = SYNC.index("name: Open or update the pin PR")
        self.assertLess(resolve, validate)
        self.assertLess(validate, tests)
        self.assertLess(tests, pr)

    def test_sync_stages_both_apps(self) -> None:
        self.assertIn("git add -A -- compatibility.yaml ftw ftw-beta", SYNC)

    def test_sync_merges_only_after_dispatching_checks(self) -> None:
        checks = SYNC.index("name: Run checks on the PR branch")
        watch = SYNC.index('gh run watch "${RUN_ID}" --exit-status')
        merge = SYNC.index("name: Merge when checks pass")
        merge_command = SYNC.index('gh pr merge "${PR}" --squash')
        publish = SYNC.index("name: Trigger publication")
        self.assertLess(checks, merge)
        self.assertLess(merge, watch)
        self.assertLess(watch, merge_command)
        self.assertLess(merge, publish)
        self.assertNotIn("--auto", SYNC)
        self.assertIn('--match-head-commit "${HEAD_SHA}"', SYNC)
        self.assertIn("--delete-branch", SYNC)
        self.assertIn("git/ref/heads/main", SYNC)

    def test_sync_dispatches_auto_publish(self) -> None:
        self.assertIn("gh workflow run auto-publish.yml --ref main", SYNC)

    def test_sync_only_logs_the_dispatch_payload(self) -> None:
        self.assertIn("github.event.client_payload", SYNC)
        self.assertNotIn("client_payload.tag", SYNC)
        self.assertNotIn("client_payload.digest", SYNC)


class AutoPublishWorkflowTests(unittest.TestCase):
    def test_publish_serializes_dispatch_without_holding_the_release_group(self) -> None:
        self.assertIn("group: ftw-publish-dispatch", AUTO_PUBLISH)
        self.assertNotIn("group: ftw-beta-publication", AUTO_PUBLISH)
        self.assertIn("cancel-in-progress: false", AUTO_PUBLISH)

    def test_publish_only_runs_in_the_canonical_repository(self) -> None:
        self.assertIn("if: github.repository == 'srcfl/home-assistant-addons'", AUTO_PUBLISH)

    def test_publish_only_dispatches_the_existing_release_workflows(self) -> None:
        self.assertIn("gh workflow run release-beta.yml --ref main", AUTO_PUBLISH)
        self.assertIn("gh workflow run promote-stable.yml --ref main", AUTO_PUBLISH)
        forbidden = (
            "build-image",
            "publish-multi-arch-manifest",
            "docker buildx imagetools create",
            "docker push",
            "packages: write",
            "gh release create",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, AUTO_PUBLISH)

    def test_publish_reads_both_app_manifests(self) -> None:
        self.assertIn("ftw-beta/config.yaml", AUTO_PUBLISH)
        self.assertIn("ftw/config.yaml", AUTO_PUBLISH)
        self.assertIn('compat["beta"].get("version") == beta_version', AUTO_PUBLISH)
        self.assertIn('stable.get("version") == stable_version', AUTO_PUBLISH)
        self.assertIn("steps.state.outputs.beta_pending == 'true'", AUTO_PUBLISH)
        self.assertIn("steps.state.outputs.stable_pending == 'true'", AUTO_PUBLISH)

    def test_beta_dispatch_guards_against_existing_and_active_releases(self) -> None:
        beta = AUTO_PUBLISH.index("name: Dispatch Publish beta")
        stable = AUTO_PUBLISH.index("name: Dispatch Promote stable")
        section = AUTO_PUBLISH[beta:stable]
        tag_guard = section.index("git/ref/tags/${tag}")
        release_guard = section.index("gh release view")
        active_guard = section.index('select(.status == "queued" or .status == "in_progress")')
        dispatch = section.index("gh workflow run release-beta.yml")
        self.assertLess(tag_guard, release_guard)
        self.assertLess(release_guard, active_guard)
        self.assertLess(active_guard, dispatch)
        self.assertIn("--workflow=finalize-beta.yml", section)

    def test_stable_dispatch_requires_the_pilot_and_the_promoted_beta_release(self) -> None:
        self.assertIn('.get("status") == "passed"', AUTO_PUBLISH)
        stable = AUTO_PUBLISH.index("name: Dispatch Promote stable")
        section = AUTO_PUBLISH[stable:]
        beta_guard = section.index('gh release view "ftw-v${BETA_VERSION}"')
        active_guard = section.index("--workflow=promote-stable.yml")
        dispatch = section.index("gh workflow run promote-stable.yml")
        self.assertLess(beta_guard, active_guard)
        self.assertLess(active_guard, dispatch)
        self.assertIn('-f "beta_digest=${BETA_DIGEST}"', section)


if __name__ == "__main__":
    unittest.main()
