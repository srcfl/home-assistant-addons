"""The publisher must reject code changes even when a pin's checks are green."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import native_pin, native_publish as publish

TAG = "v0.160.0-beta.1"
SUMS = {"amd64": "a" * 64, "arm64": "b" * 64}


def pull():
    return {"state": "open", "draft": False, "user": {"login": "github-actions[bot]"},
            "base": {"ref": "main", "repo": {"full_name": publish.REPOSITORY}},
            "head": {"ref": f"bot/pin-ftw-0x-beta-{TAG}", "repo": {"full_name": publish.REPOSITORY}}}


class PublishTest(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(publish.identity(pull()), TAG)
        for field, value in (("draft", True), ("state", "closed"),
                             ("user", {"login": "someone"})):
            pr = pull()
            pr[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                publish.identity(pr)
        for side, field, value in (("head", "repo", {"full_name": "someone/fork"}),
                                   ("base", "ref", "other"), ("head", "ref", "arbitrary")):
            pr = pull()
            pr[side][field] = value
            with self.subTest(side=side, field=field), self.assertRaises(ValueError):
                publish.identity(pr)

    def test_all_jobs_must_pass_on_the_tested_head(self):
        run = {"head_sha": "tested", "event": "workflow_dispatch", "path": ".github/workflows/check.yml",
               "conclusion": "success"}
        jobs = [{"name": name, "conclusion": "success"} for name in publish.REQUIRED_JOBS]
        publish.check_jobs(run, jobs, "tested")
        for field, value in (("head_sha", "other"), ("event", "pull_request"),
                             ("path", ".github/workflows/other.yml"), ("conclusion", "failure")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                publish.check_jobs(dict(run, **{field: value}), jobs, "tested")
        with self.assertRaises(ValueError):
            publish.check_jobs(run, jobs[1:], "tested")
        for conclusion in ("failure", "skipped", "cancelled", None):
            bad = copy.deepcopy(jobs)
            bad[0]["conclusion"] = conclusion
            with self.subTest(conclusion=conclusion), self.assertRaises(ValueError):
                publish.check_jobs(run, bad, "tested")

    def test_exact_release_diff_only(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            app = work / "ftw-0x-beta"
            app.mkdir()
            for name in publish.FILES:
                shutil.copyfile(native_pin.ROOT / name, work / name)
            previous = Path.cwd()
            os.chdir(work)
            self.addCleanup(os.chdir, previous)
            def git(*args):
                return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.com")
            git("add", ".")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            with patch.object(native_pin, "APP", app), patch.object(native_pin, "receipt", return_value=SUMS):
                native_pin.main(["native_pin.py", "bump", TAG])
                git("commit", "-am", "pin")
                head = git("rev-parse", "HEAD")
                publish.verify_change(base, head, TAG)
                with self.assertRaises(ValueError):
                    publish.verify_change(base, head, "v0.131.0-beta.1")
                for name in publish.FILES:
                    path = work / name
                    original = path.read_text()
                    path.write_text(original + "# unexpected change\n")
                    git("commit", "-am", "tamper")
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        publish.verify_change(base, git("rev-parse", "HEAD"), TAG)
                    git("reset", "--hard", head)
                (work / "unrelated").write_text("must not merge")
                git("add", ".")
                git("commit", "-m", "extra file")
                with self.assertRaises(ValueError):
                    publish.verify_change(base, git("rev-parse", "HEAD"), TAG)
            os.chdir(previous)

    def test_merge_requires_fresh_head_and_base_and_dispatches_main_check(self):
        pr = pull()
        pr["head"]["sha"] = "head"
        def responses(path, *args):
            if path == "pulls/24": return copy.deepcopy(pr)
            if path == "git/ref/heads/main": return {"object": {"sha": "base"}}
            if path == "pulls/24/merge": return {"merged": True, "sha": "merged"}
            raise AssertionError(path)
        with patch.dict(os.environ, GITHUB_REPOSITORY=publish.REPOSITORY), \
                patch.object(publish, "api", side_effect=responses) as api, \
                patch.object(publish, "command", return_value="base") as command, \
                patch.object(publish, "verify_change") as verify, patch.object(publish, "run_check") as check:
            publish.publish("24")
            verify.assert_called_once_with("base", "head", TAG)
            check.assert_called_once_with(pr["head"]["ref"], "head")
            api.assert_any_call("pulls/24/merge", "--method", "PUT", "-f", "sha=head", "-f", "merge_method=squash")
            command.assert_any_call("gh", "workflow", "run", "check.yml", "--repo", publish.REPOSITORY, "--ref", "main")

    def test_refuses_other_repository_before_any_commands(self):
        with patch.dict(os.environ, GITHUB_REPOSITORY="someone/fork"), patch.object(publish, "api") as api:
            with self.assertRaises(ValueError):
                publish.publish("123")
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
