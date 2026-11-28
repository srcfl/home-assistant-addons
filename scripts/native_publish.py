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
PIN_FILES = ("config.yaml", "Dockerfile", "CHANGELOG.md")
# Each channel's bot branch. The stable app's first pin also removes its
# unlisted manifest.
PREFIXES = {"beta": "bot/pin-ftw-0x-beta-", "stable": "bot/pin-ftw-"}
FILES = tuple(f"ftw-0x-beta/{name}" for name in PIN_FILES)


def files(channel: str) -> tuple[str, ...]:
    """Every file a pin of this channel may touch, as repository paths."""
    directory = native_pin.app_dir(channel).name
    names = PIN_FILES + ((native_pin.UNLISTED,) if channel == "stable" else ())
    return tuple(f"{directory}/{name}" for name in names)
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
    if (pr["state"] != "open" or pr["draft"] or pr["user"]["login"] != "github-actions[bot]"
            or pr["head"]["repo"]["full_name"] != REPOSITORY
            or pr["base"]["repo"]["full_name"] != REPOSITORY or pr["base"]["ref"] != "main"):
        raise ValueError("only an open, same-repository bot pin to main may publish")
    for channel, prefix in PREFIXES.items():  # beta's prefix is the longer one
        if branch.startswith(prefix):
            tag = branch[len(prefix):]
            try:
                if native_pin.channel(tag) == channel:
                    return tag
            except SystemExit:
                pass
    raise ValueError("only an open, same-repository bot pin to main may publish")


def show(commit: str, name: str) -> str | None:
    """A file at a commit, or None when it does not exist there."""
    try:
        return subprocess.check_output(["git", "show", f"{commit}:{name}"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None


def pinned_at(commit: str, channel: str) -> str | None:
    """The tag a commit pins for this channel, read with trusted code."""
    with tempfile.TemporaryDirectory() as directory:
        app = Path(directory)
        for name in files(channel):
            text = show(commit, name)
            if text is not None:
                (app / Path(name).name).write_text(text)
        with patch.object(native_pin, "APP" if channel == "beta" else "STABLE_APP", app):
            return native_pin.read_pin(channel)[0]


def verify_change(base: str, head: str, tag: str) -> None:
    """Recreate the entire diff with trusted code, never code from the PR."""
    channel = native_pin.channel(tag)
    names = files(channel)
    changed = set(command("git", "diff", "--no-renames", "--name-only", base, head).splitlines())
    with tempfile.TemporaryDirectory() as directory:
        app = Path(directory)
        before = {name: show(base, name) for name in names}
        for name, text in before.items():
            if text is not None:
                (app / Path(name).name).write_text(text)
        with patch.object(native_pin, "APP" if channel == "beta" else "STABLE_APP", app):
            old, _, _ = native_pin.read_pin(channel)
            if old is not None and native_pin.tag_order(tag) <= native_pin.tag_order(old):
                raise ValueError(f"the pin must move to a newer {channel} release")
            native_pin.main(["native_pin.py", "bump", tag])
        expected = {name: (app / Path(name).name).read_text() if (app / Path(name).name).exists() else None
                    for name in names}
    if changed != {name for name in names if expected[name] != before[name]}:
        raise ValueError("a pin must change exactly the files the release pin changes")
    for name in names:
        if show(head, name) != expected[name]:
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
            current = pinned_at(base, native_pin.channel(tag))
            if current is not None and native_pin.tag_order(tag) <= native_pin.tag_order(current):
                raise ValueError("main already contains this release or a newer one")
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
