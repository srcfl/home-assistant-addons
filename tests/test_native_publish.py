"""The publisher must reject code changes even when a pin's checks are green."""
import contextlib
import copy
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import call, patch

from scripts import native_image, native_pin, native_publish as publish

TAG = "v0.160.0-beta.1"
SUMS = {"amd64": "a" * 64, "arm64": "b" * 64}


def pull():
    return {"state": "open", "draft": False, "user": {"login": "github-actions[bot]"},
            "base": {"ref": "main", "repo": {"full_name": publish.REPOSITORY}},
            "head": {"ref": f"bot/pin-ftw-0x-beta-{TAG}", "repo": {"full_name": publish.REPOSITORY}}}


def git(*args):
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()


class PublishTest(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(publish.identity(pull()), TAG)
        pr = pull()
        pr["head"]["ref"] = "bot/pin-ftw-0x-v0.160.0"
        self.assertEqual(publish.identity(pr), "v0.160.0")
        for branch in ("bot/pin-ftw-v0.160.0", "bot/pin-ftw-0x-beta-v0.160.0", "bot/pin-ftw-0x-v0.160.0-beta.1",
                       "bot/pin-ftw-0x-v0.130.4", "bot/pin-ftw-0x-"):
            pr["head"]["ref"] = branch
            with self.subTest(branch=branch), self.assertRaises(ValueError):
                publish.identity(pr)
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
                # One minor ahead of the copied pin. A fixed tag stops being
                # newer the day FTW releases it, and the bump then changes nothing.
                newer = f"v0.{native_pin.tag_order(native_pin.read_pin()[0])[0] + 1}.0-beta.1"
                native_pin.main(["native_pin.py", "bump", newer])
                git("commit", "-am", "pin")
                head = git("rev-parse", "HEAD")
                publish.verify_change(base, head, newer)
                with self.assertRaises(ValueError):
                    publish.verify_change(base, head, "v0.131.0-beta.1")
                for name in publish.FILES:
                    path = work / name
                    original = path.read_text()
                    path.write_text(original + "# unexpected change\n")
                    git("commit", "-am", "tamper")
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        publish.verify_change(base, git("rev-parse", "HEAD"), newer)
                    git("reset", "--hard", head)
                (work / "unrelated").write_text("must not merge")
                git("add", ".")
                git("commit", "-m", "extra file")
                with self.assertRaises(ValueError):
                    publish.verify_change(base, git("rev-parse", "HEAD"), newer)
            os.chdir(previous)

    def published(self, image_error=None):
        """Run publish("24") against a fake GitHub; return its api paths and commands."""
        pr = pull()
        pr["head"]["sha"] = "head"
        paths = []

        def responses(path, *args):
            paths.append(path)
            if path == "pulls/24": return copy.deepcopy(pr)
            if path == "git/ref/heads/main": return {"object": {"sha": "base"}}
            if path == "pulls/24/merge": return {"merged": True, "sha": "merged"}
            raise AssertionError(path)
        with patch.dict(os.environ, GITHUB_REPOSITORY=publish.REPOSITORY), \
                patch.object(publish, "api", side_effect=responses) as api, \
                patch.object(publish, "command", return_value="base") as command, \
                patch.object(publish, "verify_change", return_value={"ftw-0x-beta"}) as verify, \
                patch.object(publish, "image_recipe", return_value=("recipe", "ftw-0x-beta")) as recipe, \
                patch.object(publish.native_image, "verify", side_effect=image_error) as image, \
                patch.object(publish, "run_check") as check, contextlib.redirect_stdout(io.StringIO()):
            error = None
            try:
                publish.publish("24")
            except ValueError as raised:
                error = raised
        verify.assert_called_with("base", "head", TAG)
        check.assert_called_once_with(pr["head"]["ref"], "head")
        recipe.assert_called_with("head", {"ftw-0x-beta"})
        image.assert_called_once_with(TAG[1:], "recipe")
        return api, command, paths, error

    def test_merge_requires_fresh_head_and_base_and_dispatches_main_check(self):
        api, command, _, error = self.published()
        self.assertIsNone(error)
        api.assert_any_call("pulls/24/merge", "--method", "PUT", "-f", "sha=head", "-f", "merge_method=squash")
        command.assert_any_call("gh", "workflow", "run", "check.yml", "--repo", publish.REPOSITORY, "--ref", "main")

    def test_a_pin_without_its_image_never_merges(self):
        main_check = call("gh", "workflow", "run", "check.yml", "--repo", publish.REPOSITORY, "--ref", "main")
        for reason in ("does not exist", "cannot be pulled without a login", "no signature", "another recipe"):
            with self.subTest(reason=reason):
                _, command, paths, error = self.published(native_image.ImageError(reason))
                self.assertIsInstance(error, native_image.ImageError)
                self.assertNotIn("pulls/24/merge", paths)
                self.assertNotIn(main_check, command.mock_calls)

    def test_prepare_verifies_the_pin_before_naming_its_image(self):
        pr = pull()
        pr["head"]["sha"] = "head"

        def responses(path, *args):
            if path == "pulls/24": return copy.deepcopy(pr)
            if path == "git/ref/heads/main": return {"object": {"sha": "base"}}
            raise AssertionError(path)
        with patch.dict(os.environ, GITHUB_REPOSITORY=publish.REPOSITORY), \
                patch.object(publish, "api", side_effect=responses), \
                patch.object(publish, "command", return_value="base"), \
                patch.object(publish, "verify_change", return_value={"ftw-0x-beta"}) as verify, \
                patch.object(publish, "image_recipe", return_value=("recipe", "ftw-0x-beta")) as recipe:
            self.assertEqual(publish.prepare("24"), {"head": "head", "version": TAG[1:], "recipe": "recipe",
                                                     "directory": "ftw-0x-beta"})
        verify.assert_called_once_with("base", "head", TAG)
        recipe.assert_called_once_with("head", {"ftw-0x-beta"})
        with patch.dict(os.environ, GITHUB_REPOSITORY="someone/fork"), patch.object(publish, "api") as api:
            with self.assertRaises(ValueError):
                publish.prepare("24")
            api.assert_not_called()

    def test_prepare_prints_only_outputs(self):
        def noisy(number):
            print("pinned ftw-0x-beta to v0.1.0-beta.1")
            return {"head": "h", "version": "v", "recipe": "r", "directory": "d"}
        out, err = io.StringIO(), io.StringIO()
        with patch.object(publish, "prepare", side_effect=noisy), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            publish.main(["native_publish.py", "prepare", "24"])
        self.assertEqual(out.getvalue(), "head=h\nversion=v\nrecipe=r\ndirectory=d\n")
        self.assertIn("pinned", err.getvalue())

    def test_refuses_other_repository_before_any_commands(self):
        with patch.dict(os.environ, GITHUB_REPOSITORY="someone/fork"), patch.object(publish, "api") as api:
            with self.assertRaises(ValueError):
                publish.publish("123")
            api.assert_not_called()


class StablePublishTest(unittest.TestCase):
    """The first stable pin lists the app: it adds config.yaml and removes unlisted.yaml."""

    def setUp(self):
        from tests.test_native_pin import unlisted_copy
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        unlisted_copy(self.work / "ftw-0x")
        shutil.copytree(native_pin.APP, self.work / "ftw-0x-beta")
        previous = Path.cwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        git("init")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.com")
        git("add", ".")
        git("commit", "-m", "base")
        self.base = git("rev-parse", "HEAD")
        minor = native_pin.tag_order(native_pin.read_pin()[0])[0]
        self.tag, self.above = f"v0.{minor - 1}.0", f"v0.{minor + 1}.0"  # below and above the beta pin
        for name, path in (("APP", self.work / "ftw-0x-beta"), ("STABLE_APP", self.work / "ftw-0x"),
                           ("receipt", lambda tag: SUMS)):
            patcher = patch.object(native_pin, name, path) if name != "receipt" else patch.object(native_pin, name, side_effect=path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def pin(self, tag=None):
        native_pin.main(["native_pin.py", "bump", tag or self.tag])
        git("add", "-A", "ftw-0x", "ftw-0x-beta")
        git("commit", "-m", "pin")
        return git("rev-parse", "HEAD")

    def test_first_listing_diff_only(self):
        head = self.pin()
        self.assertEqual(set(git("diff", "--no-renames", "--name-only", self.base, head).splitlines()),
                         {"ftw-0x/config.yaml", "ftw-0x/Dockerfile", "ftw-0x/CHANGELOG.md", "ftw-0x/unlisted.yaml"})
        publish.verify_change(self.base, head, self.tag)
        before, after = publish.recreate(head, self.tag)
        self.assertEqual(before, after, "a pinned release moves nothing again")
        with self.assertRaises(ValueError):
            publish.verify_change(head, head, self.tag)
        with self.assertRaises(ValueError):
            publish.verify_change(self.base, head, f"{self.tag[:-1]}1")

    def test_stable_above_the_beta_moves_both_apps_in_one_pin(self):
        head = self.pin(self.above)
        self.assertEqual(set(git("diff", "--no-renames", "--name-only", self.base, head).splitlines()),
                         {"ftw-0x/config.yaml", "ftw-0x/Dockerfile", "ftw-0x/CHANGELOG.md", "ftw-0x/unlisted.yaml",
                          "ftw-0x-beta/config.yaml", "ftw-0x-beta/Dockerfile", "ftw-0x-beta/CHANGELOG.md"})
        publish.verify_change(self.base, head, self.above)
        git("checkout", "-q", self.base, "--", "ftw-0x-beta")
        git("commit", "-q", "-m", "drop the beta half")
        with self.assertRaises(ValueError):
            publish.verify_change(self.base, git("rev-parse", "HEAD"), self.above)

    def test_the_apps_a_pin_moves_share_one_image(self):
        head = self.pin(self.above)
        moved = publish.verify_change(self.base, head, self.above)
        self.assertEqual(moved, {"ftw-0x", "ftw-0x-beta"})
        recipe, directory = publish.image_recipe(head, moved)
        self.assertEqual(directory, "ftw-0x-beta")
        self.assertEqual(recipe, native_image.recipe_of(self.work / "ftw-0x"))
        self.assertEqual(recipe, native_image.recipe_of(self.work / "ftw-0x-beta"))
        path = self.work / "ftw-0x/run.sh"
        path.write_text(path.read_text() + "# drift\n")
        git("commit", "-q", "-am", "drift")
        with self.assertRaisesRegex(ValueError, "different images"):
            publish.image_recipe(git("rev-parse", "HEAD"), moved)

    def test_a_stable_below_the_beta_builds_from_the_stable_app(self):
        head = self.pin()
        moved = publish.verify_change(self.base, head, self.tag)
        self.assertEqual(moved, {"ftw-0x"})
        self.assertEqual(publish.image_recipe(head, moved), (native_image.recipe_of(self.work / "ftw-0x"), "ftw-0x"))

    def test_listing_with_other_changes_is_refused(self):
        head = self.pin()
        for change in ("tamper", "keep unlisted", "touch beta"):
            git("reset", "-q", "--hard", head)
            if change == "tamper":
                path = self.work / "ftw-0x/config.yaml"
                path.write_text(path.read_text().replace("ingress_port: 18099", "ingress_port: 18098"))
            elif change == "keep unlisted":
                git("checkout", self.base, "--", "ftw-0x/unlisted.yaml")
            else:
                path = self.work / "ftw-0x-beta/run.sh"
                path.write_text(path.read_text() + "# unexpected change\n")
            git("add", "-A")
            git("commit", "-q", "-m", change)
            with self.subTest(change=change), self.assertRaises((ValueError, SystemExit)):
                publish.verify_change(self.base, git("rev-parse", "HEAD"), self.tag)


if __name__ == "__main__":
    unittest.main()
