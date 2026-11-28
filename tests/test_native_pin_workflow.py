"""Exercise pin-PR retries without touching GitHub or a real git branch."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parent.parent


class PinWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = pathlib.Path(self.tmp.name)
        workflow = yaml.safe_load((ROOT / ".github/workflows/sync-native.yml").read_text())
        steps = workflow["jobs"]["pin"]["steps"]
        self.script = next(step["run"] for step in steps if step.get("name") == "Open the pin pull request")
        stub = f"#!{sys.executable}\n" + textwrap.dedent('''\
            import json, os, pathlib, sys
            root = pathlib.Path(os.environ["TEST_ROOT"])
            command = pathlib.Path(sys.argv[0]).name
            args = sys.argv[1:]
            with (root / "calls").open("a") as log:
                log.write(json.dumps([command] + args) + "\\n")
            if command == "git":
                if args[0] == "ls-remote": sys.exit(0 if (root / "branch").exists() else 2)
                if args[0] == "push": (root / "branch").touch()
            elif args[:2] == ["pr", "list"]:
                state = root / "pr-state"
                print(state.read_text() if state.exists() else "")
            elif args[:2] == ["pr", "create"]:
                fail = root / "fail-create"
                if fail.exists():
                    fail.unlink()
                    sys.exit(1)
                (root / "pr-state").write_text("OPEN")
            ''' )
        for name in ("git", "gh"):
            path = self.work / name
            path.write_text(stub)
            path.chmod(0o755)

    def run_pin(self, tag="v0.160.0-beta.1", apps="ftw-0x-beta"):
        env = dict(os.environ, PATH=f"{self.work}:{os.environ['PATH']}",
                   TEST_ROOT=str(self.work), TAG=tag, APPS=apps, GH_TOKEN="test-only")
        env["GITHUB_OUTPUT"] = str(self.work / "outputs")
        result = subprocess.run(["bash", "-c", self.script], env=env,
                                capture_output=True, text=True)
        calls = [json.loads(line) for line in (self.work / "calls").read_text().splitlines()]
        return result, calls

    def test_retry_recovers_pushed_branch_and_opens_one_pr(self):
        (self.work / "fail-create").touch()
        first, _ = self.run_pin()
        self.assertNotEqual(first.returncode, 0)
        second, calls = self.run_pin()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(sum(call[:2] == ["git", "push"] for call in calls), 1)
        self.assertEqual(sum(call[:3] == ["gh", "pr", "create"] for call in calls), 2)
        third, calls = self.run_pin()
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertEqual(sum(call[:3] == ["gh", "pr", "create"] for call in calls), 2)

    def test_one_branch_per_release_and_the_title_names_the_apps(self):
        for tag, apps, branch in (("v0.160.0-beta.1", "ftw-0x-beta", "bot/pin-ftw-0x-beta-v0.160.0-beta.1"),
                                  ("v0.160.0", "ftw-0x and ftw-0x-beta", "bot/pin-ftw-0x-v0.160.0")):
            with self.subTest(tag=tag):
                for name in ("branch", "pr-state", "calls"):
                    (self.work / name).unlink(missing_ok=True)
                result, calls = self.run_pin(tag, apps)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(["git", "push", "origin", branch], calls)
                # The first stable pin adds config.yaml, which `commit -a` would miss.
                self.assertIn(["git", "add", "-A", "--", "ftw-0x-beta", "ftw-0x"], calls)
                self.assertIn(["git", "commit", "-m", f"chore: pin {apps} to FTW {tag}"], calls)
                create = next(call for call in calls if call[:3] == ["gh", "pr", "create"])
                self.assertEqual(create[create.index("--title") + 1], f"chore: pin {apps} to FTW {tag}")

    def test_closed_pin_is_not_reopened(self):
        (self.work / "branch").touch()
        (self.work / "pr-state").write_text("CLOSED")
        result, calls = self.run_pin()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[:3] == ["gh", "pr", "create"] for call in calls))
        self.assertFalse(any(call[:3] == ["gh", "workflow", "run"] for call in calls))


class ImageFlowTest(unittest.TestCase):
    """The pin workflow builds and signs the image before it can merge the pin."""

    def setUp(self):
        self.workflow = yaml.load((ROOT / ".github/workflows/sync-native.yml").read_text(), Loader=yaml.BaseLoader)
        self.jobs = self.workflow["jobs"]

    def steps(self, job):
        return self.jobs[job]["steps"]

    def step(self, job, name):
        return next(step for step in self.steps(job) if step.get("name") == name)

    def test_jobs_run_in_order(self):
        self.assertEqual(list(self.jobs), ["pin", "image", "publish"])
        self.assertEqual(self.jobs["image"]["needs"], "pin")
        self.assertEqual(self.jobs["publish"]["needs"], ["pin", "image"])
        # A plain success() gate: a failed or skipped image job stops the merge.
        self.assertNotIn("if", self.jobs["publish"])
        self.assertEqual(self.jobs["image"]["if"], "needs.pin.outputs.number != ''")

    def test_only_the_image_job_writes_packages_or_signs(self):
        for name, job in self.jobs.items():
            permissions = job.get("permissions", {})
            with self.subTest(job=name):
                if name == "image":
                    self.assertEqual(permissions, {"contents": "read", "packages": "write", "id-token": "write"})
                else:
                    self.assertNotIn("packages", permissions)
                    self.assertNotIn("id-token", permissions)
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})

    def test_each_architecture_builds_on_its_own_runner(self):
        from scripts import native_image
        matrix = self.jobs["image"]["strategy"]["matrix"]["include"]
        self.assertEqual({entry["arch"]: entry["os"] for entry in matrix},
                         {"amd64": "ubuntu-24.04", "aarch64": "ubuntu-24.04-arm"})
        self.assertEqual(tuple(entry["arch"] for entry in matrix), native_image.ARCHES)

    def test_the_image_job_builds_the_verified_commit(self):
        prepare = self.step("pin", "Verify the pin and name its image")
        names = [step.get("name") for step in self.steps("pin")]
        self.assertLess(names.index("Open the pin pull request"), names.index(prepare["name"]))
        self.assertIn("native_publish prepare", prepare["run"])
        checkout = self.steps("image")[0]
        self.assertTrue(checkout["uses"].startswith("actions/checkout@"))
        self.assertEqual(checkout["with"], {"ref": "${{ needs.pin.outputs.head }}", "persist-credentials": "false"})
        found = self.step("image", "Look for this version's image")["run"]
        self.assertIn('test "$(git rev-parse HEAD)" = "${HEAD}"', found)
        self.assertIn('native_image recipe "${APP_DIR}")" = "${RECIPE}"', found)

    def test_build_smoke_push_and_sign_in_that_order(self):
        names = [step.get("name") or step.get("uses") for step in self.steps("image")]
        build = names.index("Build from the pinned release package")
        smoke = names.index("Smoke the image under Supervisor-like conditions")
        push = names.index("Push to a new tag and sign the pushed digest")
        self.assertLess(build, smoke)
        self.assertLess(smoke, push)
        run = self.step("image", "Build from the pinned release package")["run"]
        for part in ("--pull", '"BUILD_ARCH=${ARCH}"', '"BUILD_VERSION=${VERSION}"',
                     '"com.sourceful.ftw.recipe=${RECIPE}"', '"${APP_DIR}"'):
            self.assertIn(part, run)
        self.assertIn("scripts/smoke_native.sh", self.step("image", names[smoke])["run"])
        self.assertIn("native_image push", self.step("image", names[push])["run"])
        for step in self.steps("image")[3:]:
            if step.get("name") != "Look for this version's image":
                self.assertEqual(step.get("if"), "steps.found.outputs.digest == ''", step)
        text = (ROOT / ".github/workflows/sync-native.yml").read_text()
        for forbidden in ("docker tag", "imagetools create", "--force", ":latest"):
            self.assertNotIn(forbidden, text)

    def test_publish_verifies_without_a_registry_login(self):
        uses = [step.get("uses", "") for step in self.steps("publish")]
        self.assertFalse(any(use.startswith("docker/login-action") for use in uses))
        self.assertTrue(any(use.startswith("sigstore/cosign-installer@") for use in uses))
        self.assertIn("native_publish publish", self.step("publish", "Check, verify the images and merge")["run"])

    def test_main_checks_its_images(self):
        check = yaml.load((ROOT / ".github/workflows/check.yml").read_text(), Loader=yaml.BaseLoader)
        steps = check["jobs"]["repository"]["steps"]
        verify = next(step for step in steps if "verify-main" in step.get("run", ""))
        self.assertEqual(verify["if"], "github.ref == 'refs/heads/main'")
        self.assertTrue(any(step.get("uses", "").startswith("sigstore/cosign-installer@")
                            and step.get("if") == verify["if"] for step in steps))


if __name__ == "__main__":
    unittest.main()
