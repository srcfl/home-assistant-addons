#!/usr/bin/env python3
"""Publish only a verified bot pin after Check passes on its exact commit."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from scripts import native_pin

REPOSITORY = "srcfl/home-assistant-addons"
FILES = tuple(f"ftw-0x-beta/{name}" for name in ("config.yaml", "Dockerfile", "CHANGELOG.md"))
REQUIRED_JOBS = {
    "Repository and shell checks", "Home Assistant app lint", "Prepare native build matrix",
    "Build and smoke amd64", "Build and smoke aarch64",
    "Native beta build and smoke amd64", "Native beta build and smoke aarch64",
}


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def gh(*args: str):
    return json.loads(command("gh", *args))


def api(path: str, *args: str):
    return gh("api", f"repos/{REPOSITORY}/{path}", *args)


def identity(pr: dict) -> str:
    branch = pr["head"]["ref"]
    prefix = "bot/pin-ftw-0x-beta-"
    if (pr["state"] != "open" or pr["draft"] or pr["user"]["login"] != "github-actions[bot]"
            or pr["head"]["repo"]["full_name"] != REPOSITORY
            or pr["base"]["repo"]["full_name"] != REPOSITORY or pr["base"]["ref"] != "main"
            or not branch.startswith(prefix)):
        raise ValueError("only an open, same-repository bot pin to main may publish")
    tag = branch[len(prefix):]
    native_pin.tag_order(tag)
    return tag


def verify_change(base: str, head: str, tag: str) -> None:
    """Recreate the entire diff with trusted code, never code from the PR."""
    changed = command("git", "diff", "--name-only", base, head).splitlines()
    if set(changed) != set(FILES):
        raise ValueError("a pin must change exactly config.yaml, Dockerfile and CHANGELOG.md")
    with tempfile.TemporaryDirectory() as directory:
        app = Path(directory)
        for name in FILES:
            (app / Path(name).name).write_text(subprocess.check_output(["git", "show", f"{base}:{name}"], text=True))
        with patch.object(native_pin, "APP", app):
            old, _, _ = native_pin.read_pin()
            if native_pin.tag_order(tag) <= native_pin.tag_order(old):
                raise ValueError("the pin must move to a newer beta")
            native_pin.main(["native_pin.py", "bump", tag])
        for name in FILES:
            expected = (app / Path(name).name).read_text()
            actual = subprocess.check_output(["git", "show", f"{head}:{name}"], text=True)
            if actual != expected:
                raise ValueError(f"{name} contains changes outside the verified release pin")


def check_jobs(run: dict, jobs: list[dict], head: str) -> None:
    if (run["head_sha"] != head or run["event"] != "workflow_dispatch"
            or run["path"] != ".github/workflows/check.yml"
            or run["conclusion"] != "success"):
        raise ValueError("Check did not pass on this exact pin commit")
    successful = {job["name"] for job in jobs if job["conclusion"] == "success"}
    if not REQUIRED_JOBS <= successful:
        raise ValueError("Check is missing successful required jobs")
    if any(job["conclusion"] != "success" for job in jobs):
        raise ValueError("Check contains a failed or skipped job")


def run_check(branch: str, head: str) -> None:
    since = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    command("gh", "workflow", "run", "check.yml", "--repo", REPOSITORY, "--ref", branch)
    for _ in range(36):
        runs = gh("run", "list", "--repo", REPOSITORY, "--workflow", "check.yml", "--branch", branch,
                  "--event", "workflow_dispatch", "--json", "databaseId,headSha,createdAt")
        matches = [run for run in runs if run["headSha"] == head and run["createdAt"] >= since]
        if matches:
            run_id = str(max(matches, key=lambda run: run["databaseId"])["databaseId"])
            command("gh", "run", "watch", run_id, "--repo", REPOSITORY, "--exit-status", "--interval", "15")
            run = api(f"actions/runs/{run_id}")
            # GitHub can finish the run before the jobs API catches up.
            for _ in range(24):
                jobs = api(f"actions/runs/{run_id}/jobs?per_page=100")["jobs"]
                if all(job["status"] == "completed" for job in jobs):
                    check_jobs(run, jobs, head)
                    return
                time.sleep(5)
            raise ValueError("Check jobs did not report their final status")
        time.sleep(5)
    raise ValueError("the dispatched Check run did not appear")


def publish(number: str) -> None:
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("publication is restricted to the canonical repository")
    for _ in range(4):
        pr = api(f"pulls/{number}")
        tag = identity(pr)
        head = pr["head"]["sha"]
        base = api("git/ref/heads/main")["object"]["sha"]
        command("git", "fetch", "origin", base, head)
        ancestor = command("git", "merge-base", base, head)
        verify_change(ancestor, head, tag)
        if ancestor != base:
            # Do not replay a delayed event over a newer version on main.
            with tempfile.TemporaryDirectory() as directory:
                app = Path(directory)
                for name in FILES[:2]:
                    (app / Path(name).name).write_text(subprocess.check_output(["git", "show", f"{base}:{name}"], text=True))
                with patch.object(native_pin, "APP", app):
                    current, _, _ = native_pin.read_pin()
                if native_pin.tag_order(tag) <= native_pin.tag_order(current):
                    raise ValueError("main already contains this beta or a newer one")
            api(f"pulls/{number}/update-branch", "--method", "PUT", "-f", f"expected_head_sha={head}")
            time.sleep(5)
            continue
        run_check(pr["head"]["ref"], head)
        fresh = api(f"pulls/{number}")
        identity(fresh)
        if fresh["head"]["sha"] != head:
            raise ValueError("the PR changed while Check ran")
        if api("git/ref/heads/main")["object"]["sha"] != base:
            continue  # Refresh the base and test the resulting commit again.
        result = api(f"pulls/{number}/merge", "--method", "PUT", "-f", f"sha={head}",
                     "-f", "merge_method=squash")
        if not result.get("merged"):
            raise ValueError("GitHub refused the pin merge")
        print(f"Published {tag}: {result['sha']}")
        # GITHUB_TOKEN merges do not trigger push workflows.
        command("gh", "workflow", "run", "check.yml", "--repo", REPOSITORY, "--ref", "main")
        return
    raise ValueError("main kept changing; rerun the pin workflow to retry")


if __name__ == "__main__":
    publish(sys.argv[1])
