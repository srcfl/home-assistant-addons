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

    def run_pin(self):
        env = dict(os.environ, PATH=f"{self.work}:{os.environ['PATH']}",
                   TEST_ROOT=str(self.work), TAG="v0.160.0-beta.1", GH_TOKEN="test-only")
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

    def test_closed_pin_is_not_reopened(self):
        (self.work / "branch").touch()
        (self.work / "pr-state").write_text("CLOSED")
        result, calls = self.run_pin()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[:3] == ["gh", "pr", "create"] for call in calls))
        self.assertFalse(any(call[:3] == ["gh", "workflow", "run"] for call in calls))


if __name__ == "__main__":
    unittest.main()
