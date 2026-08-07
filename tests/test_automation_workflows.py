from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SYNC = (ROOT / ".github/workflows/sync-upstream.yml").read_text(encoding="utf-8")
AUTO_PUBLISH = (ROOT / ".github/workflows/auto-publish-beta.yml").read_text(encoding="utf-8")


class SyncWorkflowTests(unittest.TestCase):
    def test_sync_watches_upstream_releases_and_the_clock(self) -> None:
        self.assertIn("repository_dispatch:", SYNC)
        self.assertIn("types: [ftw-release]", SYNC)
        self.assertIn("schedule:", SYNC)

    def test_sync_serializes_its_runs(self) -> None:
        self.assertIn("group: ftw-upstream-sync", SYNC)
        self.assertIn("cancel-in-progress: false", SYNC)

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
        validate = SYNC.index("python scripts/validate.py --channel beta")
        tests = SYNC.index("python -m unittest discover")
        pr = SYNC.index("name: Open or update the pin PR")
        self.assertLess(resolve, validate)
        self.assertLess(validate, tests)
        self.assertLess(tests, pr)

    def test_sync_merges_only_after_dispatching_checks(self) -> None:
        checks = SYNC.index("name: Run checks on the PR branch")
        watch = SYNC.index('gh run watch "${RUN_ID}" --exit-status')
        merge = SYNC.index("name: Merge when checks pass")
        merge_command = SYNC.index('gh pr merge "${PR}" --squash')
        publish = SYNC.index("name: Trigger beta publication")
        self.assertLess(checks, merge)
        self.assertLess(merge, watch)
        self.assertLess(watch, merge_command)
        self.assertLess(merge, publish)
        self.assertNotIn("--auto", SYNC)
        self.assertIn('--match-head-commit "${HEAD_SHA}"', SYNC)
        self.assertIn('--delete-branch', SYNC)
        self.assertIn('git/ref/heads/main', SYNC)


class AutoPublishWorkflowTests(unittest.TestCase):
    def test_publish_serializes_dispatch_without_holding_the_release_group(self) -> None:
        self.assertIn("group: ftw-beta-dispatch", AUTO_PUBLISH)
        self.assertNotIn("group: ftw-beta-publication", AUTO_PUBLISH)
        self.assertIn("cancel-in-progress: false", AUTO_PUBLISH)

    def test_publish_only_runs_in_the_canonical_repository(self) -> None:
        self.assertIn("if: github.repository == 'srcfl/home-assistant-addons'", AUTO_PUBLISH)

    def test_publish_only_dispatches_the_existing_release_workflow(self) -> None:
        self.assertIn("gh workflow run release-beta.yml --ref main", AUTO_PUBLISH)
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

    def test_publish_requires_the_pending_beta_marker(self) -> None:
        self.assertIn("__PUBLISHED_BY_BETA_WORKFLOW__", AUTO_PUBLISH)
        self.assertIn('add_on.get("channel") == "beta"', AUTO_PUBLISH)
        self.assertIn('add_on.get("version") == version', AUTO_PUBLISH)
        self.assertIn("steps.state.outputs.pending == 'true'", AUTO_PUBLISH)

    def test_publish_guards_against_existing_and_active_releases(self) -> None:
        tag_guard = AUTO_PUBLISH.index("git/ref/tags/${tag}")
        release_guard = AUTO_PUBLISH.index("gh release view")
        active_guard = AUTO_PUBLISH.index('select(.status == "queued" or .status == "in_progress")')
        dispatch = AUTO_PUBLISH.index("gh workflow run release-beta.yml")
        self.assertLess(tag_guard, release_guard)
        self.assertLess(release_guard, active_guard)
        self.assertLess(active_guard, dispatch)
        self.assertIn("--workflow=finalize-beta.yml", AUTO_PUBLISH)


if __name__ == "__main__":
    unittest.main()
