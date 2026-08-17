#!/usr/bin/env python3
"""Sync the add-on pins to the latest upstream FTW Core and Optimizer releases.

The sync only moves forward: it selects the highest published upstream
release, resolves the multi-arch image digest and source commit from the
registry, and rewrites the pins so that the existing fail-closed release
gates accept them. It never downgrades and it skips releases whose images
are not fully published yet.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any, Callable

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
UPSTREAM_REPOSITORY = "srcfl/ftw"
CORE_IMAGE = "ghcr.io/srcfl/ftw"
OPTIMIZER_IMAGE = "ghcr.io/srcfl/ftw-optimizer"
PUBLISHER_MARKER = "__PUBLISHED_BY_BETA_WORKFLOW__"
CORE_TAG = re.compile(r"^v\d+\.\d+\.\d+(?:-beta\.\d+)?$")
OPTIMIZER_TAG = re.compile(r"^optimizer-v\d+\.\d+\.\d+(?:-beta\.\d+)?$")
UPSTREAM_VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")
ADD_ON_BETA = re.compile(r"^(\d+)\.(\d+)\.(\d+)-beta\.(\d+)$")
ADD_ON_STABLE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
LIVE_PILOT_URL = re.compile(
    r"^https://github\.com/srcfl/ftw/"
    r"(?:(?:pull|issues)/\d+#issuecomment-\d+|actions/runs/\d+(?:[/?#][^\s]*)?)$"
)
ABSENT_IMAGE_MARKERS = ("manifest unknown", "name unknown", "not found")
MAX_VERSION_PROBES = 200
PILOT_EXPECTED = {
    "install": "Supervisor pulls the signed pre-built image for the host architecture.",
    "boot_readiness": "Setup opens, then health reports valid Core status after state migration.",
    "persistence": (
        "Config, state, history, user drivers, and managed drivers survive app and host restarts."
    ),
    "optimizer_fallback": "Socket, handshake, and solve failures keep Core ready on the Go planner.",
    "optimizer_recovery": (
        "The Unix worker reconnects after capped retry without a container restart or hidden Python worker."
    ),
    "update": "Supervisor updates from the exact prior signed beta with no FTW updater or Docker socket.",
    "rollback": (
        "Supervisor rolls back the image, then the operator restores the matching HA backup and data state."
    ),
    "artifact_match": "The pulled multi-architecture digest matches the signed beta release record.",
    "active_solver": "Unix handshake and solve use protocol 1, plan schema 1, and all requested features.",
}


class SyncError(Exception):
    pass


class ImageNotReady(Exception):
    """The release exists but its multi-arch image is not fully published yet."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SyncError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def command_output(command: list[str]) -> str:
    result = run(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SyncError(f"command failed ({' '.join(command)}): {detail}")
    return result.stdout.strip()


def gh_api(path: str) -> Any:
    return json.loads(command_output(["gh", "api", path]))


def gh_api_optional(path: str) -> Any | None:
    result = run(["gh", "api", path])
    if result.returncode == 0:
        return json.loads(result.stdout)
    detail = f"{result.stdout}\n{result.stderr}".lower()
    if "not found" in detail or "404" in detail:
        return None
    raise SyncError(f"could not query {path}: {(result.stderr or result.stdout).strip()}")


def version_key(version: str) -> tuple[int, int, int, int, int] | None:
    match = UPSTREAM_VERSION.fullmatch(version)
    if match is None:
        return None
    major, minor, patch, beta = match.groups()
    if beta is None:
        return (int(major), int(minor), int(patch), 1, 0)
    return (int(major), int(minor), int(patch), 0, int(beta))


def release_version(tag: str) -> str:
    return tag.removeprefix("optimizer-")


def select_latest_release(releases: list[Any], tag_pattern: re.Pattern[str]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_key: tuple[int, int, int, int, int] | None = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = str(release.get("tag_name", ""))
        if tag_pattern.fullmatch(tag) is None:
            continue
        key = version_key(release_version(tag))
        if key is None:
            continue
        if best_key is None or key > best_key:
            best, best_key = release, key
    return best


def next_add_on_version(current: str, tag_exists: Callable[[str], bool]) -> str:
    beta = ADD_ON_BETA.fullmatch(current)
    if beta is not None:
        major, minor, patch = beta.group(1), beta.group(2), beta.group(3)
        number = int(beta.group(4)) + 1
    else:
        stable = ADD_ON_STABLE.fullmatch(current)
        require(stable is not None, f"current add-on version is invalid: {current}")
        major, minor = stable.group(1), stable.group(2)
        patch = str(int(stable.group(3)) + 1)
        number = 1
    for _ in range(MAX_VERSION_PROBES):
        candidate = f"{major}.{minor}.{patch}-beta.{number}"
        if not tag_exists(f"ftw-v{candidate}"):
            return candidate
        number += 1
    raise SyncError("could not find a free add-on beta version")


def strip_url(url: str) -> str:
    return url.rstrip(".,;:!?'\"")


def extract_live_pilot_evidence(body: str | None) -> str | None:
    text = body or ""
    labeled = re.search(
        r"live[\s_-]?pilot[^\n]*?(https://github\.com/srcfl/ftw/[^\s<>()\[\]]+)",
        text,
        re.IGNORECASE,
    )
    if labeled is not None:
        url = strip_url(labeled.group(1))
        if LIVE_PILOT_URL.fullmatch(url) is not None:
            return url
    return None


def image_labels(image: dict[str, Any]) -> dict[str, str]:
    config = image.get("config") or image.get("Config")
    require(isinstance(config, dict), "image config is missing")
    labels = config.get("Labels") or config.get("labels")
    require(isinstance(labels, dict), "image labels are missing")
    return {str(key): str(value) for key, value in labels.items()}


def allowed_oci_version_labels(image: str, release_version: str) -> set[str]:
    if image != CORE_IMAGE:
        return {release_version}
    match = UPSTREAM_VERSION.fullmatch(release_version)
    require(match is not None, f"Core release version is invalid: {release_version}")
    major, minor, patch, beta = match.groups()
    package_version = f"{major}.{minor}.{patch}"
    if beta is None:
        return {package_version}
    return {release_version, package_version}


def optional_image_digest(reference: str) -> str | None:
    result = run(["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"])
    if result.returncode == 0:
        digest = result.stdout.strip()
        require(DIGEST.fullmatch(digest) is not None, f"registry returned an invalid digest for {reference}")
        return digest
    detail = f"{result.stdout}\n{result.stderr}".lower()
    if any(marker in detail for marker in ABSENT_IMAGE_MARKERS):
        return None
    raise SyncError(f"could not check image tag {reference}: {(result.stderr or result.stdout).strip()}")


def inspect_release_image(image: str, version: str, expected_commit: str) -> str:
    """Resolve the release digest and require the labels the release gate will re-check."""
    digest = None
    for tag in dict.fromkeys((version, version.removeprefix("v"))):
        digest = optional_image_digest(f"{image}:{tag}")
        if digest is not None:
            break
    if digest is None:
        raise ImageNotReady(f"{image} has no published image for {version} yet")
    index = json.loads(command_output(["docker", "buildx", "imagetools", "inspect", f"{image}@{digest}", "--raw"]))
    require(isinstance(index, dict), f"{image} registry index is invalid")
    manifests = index.get("manifests")
    require(isinstance(manifests, list), f"{image} pin must resolve to a multi-arch index")
    for architecture in ("amd64", "arm64"):
        descriptor = next(
            (
                item
                for item in manifests
                if isinstance(item, dict)
                and item.get("platform", {}).get("os") == "linux"
                and item.get("platform", {}).get("architecture") == architecture
            ),
            None,
        )
        if descriptor is None:
            raise ImageNotReady(f"{image}@{digest} lacks linux/{architecture} yet")
        child = json.loads(
            command_output(
                [
                    "docker",
                    "buildx",
                    "imagetools",
                    "inspect",
                    f"{image}@{descriptor['digest']}",
                    "--format",
                    "{{json .Image}}",
                ]
            )
        )
        require(isinstance(child, dict), f"{image} linux/{architecture} config is invalid")
        labels = image_labels(child)
        require(
            labels.get("org.opencontainers.image.version") in allowed_oci_version_labels(image, version),
            f"{image} linux/{architecture} version label does not match release {version}",
        )
        require(
            labels.get("org.opencontainers.image.revision") == expected_commit,
            f"{image} linux/{architecture} revision label does not match the release commit",
        )
    return digest


def discover_build_run(repository: str, commit: str) -> str | None:
    try:
        record = gh_api(f"repos/{repository}/actions/runs?head_sha={commit}&status=success&per_page=100")
    except SyncError:
        return None
    runs = record.get("workflow_runs") if isinstance(record, dict) else None
    if not isinstance(runs, list):
        return None
    fallback = None
    for entry in runs:
        if not isinstance(entry, dict):
            continue
        url = entry.get("html_url")
        if not isinstance(url, str):
            continue
        label = f"{entry.get('name', '')} {entry.get('path', '')}".lower()
        if "build" in label or "release" in label:
            return url
        fallback = fallback or url
    return fallback


def resolve_pin(
    *,
    upstream: str,
    release: dict[str, Any],
    image: str,
    current_version: str,
) -> dict[str, Any] | None:
    tag = str(release.get("tag_name", ""))
    version = release_version(tag)
    if version == current_version:
        return None
    current_key = version_key(current_version)
    new_key = version_key(version)
    if current_key is not None and new_key is not None and new_key <= current_key:
        return None
    commit = str(gh_api(f"repos/{upstream}/commits/{tag}").get("sha", ""))
    require(COMMIT.fullmatch(commit) is not None, f"could not resolve the commit for {tag}")
    digest = inspect_release_image(image, version, commit)
    return {
        "version": version,
        "digest": digest,
        "commit": commit,
        "release_url": str(release.get("html_url", "")),
        "build_url": discover_build_run(upstream, commit),
        "body": str(release.get("body") or ""),
    }


def render_pilot_record(compat: dict[str, Any], version: str, update_from: str | None) -> dict[str, Any]:
    core = compat["core"]
    optimizer = compat["optimizer"]
    drivers = compat["drivers"]
    baseline = drivers["tested_baseline"]
    checks: dict[str, Any] = {}
    for name in ("install", "boot_readiness", "persistence", "optimizer_fallback", "optimizer_recovery"):
        checks[name] = {"status": "blocked", "expected": PILOT_EXPECTED[name], "evidence": None}
    checks["update"] = {
        "status": "blocked",
        "from_version": update_from,
        "from_manifest_digest": None,
        "to_version": version,
        "to_manifest_digest": None,
        "expected": PILOT_EXPECTED["update"],
        "evidence": None,
    }
    checks["rollback"] = {
        "status": "blocked",
        "from_version": version,
        "from_manifest_digest": None,
        "to_version": update_from,
        "to_manifest_digest": None,
        "backup_reference": None,
        "expected": PILOT_EXPECTED["rollback"],
        "evidence": None,
    }
    for name in ("artifact_match", "active_solver"):
        checks[name] = {"status": "blocked", "expected": PILOT_EXPECTED[name], "evidence": None}
    return {
        "schema_version": 1,
        "add_on_version": version,
        "status": "blocked",
        "candidate": {
            "source_commit": None,
            "manifest_digest": None,
            "core": {
                "version": core["version"],
                "commit": core["commit"],
                "digest": core["digest"],
            },
            "optimizer": {
                "version": optimizer["version"],
                "commit": optimizer["commit"],
                "digest": optimizer["digest"],
            },
            "drivers": {
                "channel": drivers["channel"],
                "tested_commit": baseline["commit"],
                "manifest_sha256": baseline["manifest_sha256"],
                "key_id": baseline["key_id"],
            },
        },
        "environment": {
            "host_architecture": None,
            "hardware": None,
            "home_assistant_os_version": None,
            "supervisor_version": None,
            "operator": None,
            "started_at": None,
            "completed_at": None,
        },
        "checks": checks,
        "notes": "Automated upstream sync. All Home Assistant OS and Supervisor checks remain blocked.",
    }


def replace_config_version(text: str, version: str) -> str:
    new_text, count = re.subn(r'(?m)^version: "[^"]*"$', f'version: "{version}"', text)
    require(count == 1, "ftw/config.yaml version line was not found")
    new_text, count = re.subn(
        r'(?m)^  FTW_BUNDLE_VERSION: "[^"]*"$',
        f'  FTW_BUNDLE_VERSION: "{version}"',
        new_text,
    )
    require(count == 1, "ftw/config.yaml FTW_BUNDLE_VERSION line was not found")
    return new_text


def prepend_changelog(text: str, version: str, core_pin: dict[str, Any] | None, optimizer_pin: dict[str, Any] | None) -> str:
    marker = "# Changelog\n\n"
    require(text.startswith(marker), "ftw/CHANGELOG.md header is missing")
    lines = []
    if core_pin is not None:
        lines.append(f"- Update Core to {core_pin['version']}.")
    if optimizer_pin is not None:
        lines.append(f"- Update Optimizer to {optimizer_pin['version']}.")
    lines.append(
        "- Automated upstream pin sync. Home Assistant OS and Supervisor"
        " qualification is still required before stable promotion."
    )
    entry = f"## {version}\n\n" + "\n".join(lines) + "\n\n"
    return marker + entry + text[len(marker):]


def compose_updates(
    *,
    compat: dict[str, Any],
    config_text: str,
    changelog_text: str,
    core_pin: dict[str, Any] | None,
    optimizer_pin: dict[str, Any] | None,
    new_version: str,
    update_from: str | None,
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    updated = copy.deepcopy(compat)
    add_on = updated["add_on"]
    add_on["version"] = new_version
    add_on["channel"] = "beta"
    add_on["manifest_digest"] = PUBLISHER_MARKER
    upstream_gate = updated["qualification"]["upstream_gate"]
    evidence = dict(upstream_gate.get("evidence") or {})
    if core_pin is not None:
        live_pilot = extract_live_pilot_evidence(core_pin["body"])
        require(
            live_pilot is not None,
            f"Core {core_pin['version']} release lacks labeled live-pilot evidence",
        )
        core = updated["core"]
        core["version"] = core_pin["version"]
        core["digest"] = core_pin["digest"]
        core["commit"] = core_pin["commit"]
        evidence["core_release"] = core_pin["release_url"]
        evidence["core_build"] = core_pin["build_url"]
        evidence["core_live_pilot"] = live_pilot
    if optimizer_pin is not None:
        optimizer = updated["optimizer"]
        optimizer["version"] = optimizer_pin["version"]
        optimizer["digest"] = optimizer_pin["digest"]
        optimizer["commit"] = optimizer_pin["commit"]
        evidence["optimizer_release"] = optimizer_pin["release_url"]
        evidence["optimizer_build"] = optimizer_pin["build_url"]
    upstream_gate["status"] = "passed"
    upstream_gate["evidence"] = evidence
    updated["qualification"]["home_assistant_os_supervisor"] = {
        "status": "blocked",
        "evidence": None,
        "record": f"pilot/{new_version}.yaml",
    }
    updated["qualification"]["promoted_from_beta"] = {
        "channel": None,
        "version": None,
        "manifest_digest": None,
        "source_commit": None,
    }
    config_new = replace_config_version(config_text, new_version)
    changelog_new = prepend_changelog(changelog_text, new_version, core_pin, optimizer_pin)
    pilot = render_pilot_record(updated, new_version, update_from)
    return updated, config_new, changelog_new, pilot


class YamlDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)


def dump_yaml(value: dict[str, Any]) -> str:
    return yaml.dump(
        value,
        Dumper=YamlDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    )


def render_pr_body(
    *,
    previous: dict[str, str],
    new_version: str,
    compat: dict[str, Any],
    core_pin: dict[str, Any] | None,
    optimizer_pin: dict[str, Any] | None,
) -> str:
    def cell(pin: dict[str, Any] | None, current: str) -> str:
        if pin is None:
            return f"{current} (unchanged)"
        return f"[{pin['version']}]({pin['release_url']})"

    evidence = compat["qualification"]["upstream_gate"]["evidence"]
    details = []
    for name, pin in (("Core", core_pin), ("Optimizer", optimizer_pin)):
        if pin is None:
            continue
        details.append(f"- {name} `{pin['version']}` at commit `{pin['commit']}`")
        details.append(f"  - Digest: `{pin['digest']}`")
        details.append(f"  - Release: {pin['release_url']}")
        if pin["build_url"]:
            details.append(f"  - Build: {pin['build_url']}")
    if core_pin is not None:
        details.append(f"- Core live-pilot evidence: {evidence['core_live_pilot']}")
    baseline = compat["drivers"]["tested_baseline"]
    details.append(f"- Drivers: unchanged tested baseline `{baseline['commit']}`")
    detail_text = "\n".join(details)
    return f"""Automated upstream pin sync.

| Component | From | To |
| --- | --- | --- |
| Add-on | {previous['add_on']} | {new_version} |
| Core | {previous['core']} | {cell(core_pin, previous['core'])} |
| Optimizer | {previous['optimizer']} | {cell(optimizer_pin, previous['optimizer'])} |

Merging this PR lets **Auto publish beta** dispatch **Publish beta**, which
builds, signs, and releases `{new_version}` on the beta channel. All release
gates still apply.

<details>
<summary>Exact pins, commits, and evidence</summary>

{detail_text}

</details>
"""


def write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with pathlib.Path(output).open("a", encoding="utf-8") as target:
            target.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def sync(args: argparse.Namespace) -> None:
    compat = load_yaml(ROOT / "compatibility.yaml")
    config_text = (ROOT / "ftw/config.yaml").read_text(encoding="utf-8")
    changelog_text = (ROOT / "ftw/CHANGELOG.md").read_text(encoding="utf-8")
    previous = {
        "add_on": str(compat["add_on"]["version"]),
        "core": str(compat["core"]["version"]),
        "optimizer": str(compat["optimizer"]["version"]),
    }

    releases = gh_api(f"repos/{args.upstream}/releases?per_page=100")
    require(isinstance(releases, list), "upstream releases response is invalid")
    core_release = select_latest_release(releases, CORE_TAG)
    optimizer_release = select_latest_release(releases, OPTIMIZER_TAG)
    require(core_release is not None, "no Core release was found upstream")
    require(optimizer_release is not None, "no Optimizer release was found upstream")

    try:
        core_pin = resolve_pin(
            upstream=args.upstream,
            release=core_release,
            image=CORE_IMAGE,
            current_version=previous["core"],
        )
        optimizer_pin = resolve_pin(
            upstream=args.upstream,
            release=optimizer_release,
            image=OPTIMIZER_IMAGE,
            current_version=previous["optimizer"],
        )
    except ImageNotReady as error:
        print(f"::notice::upstream release is not ready yet, retrying later: {error}")
        write_output("changed", "false")
        return

    if core_pin is None and optimizer_pin is None:
        print("pins already match the latest upstream releases")
        write_output("changed", "false")
        return

    if core_pin is not None and extract_live_pilot_evidence(core_pin["body"]) is None:
        print(
            f"::notice::Core {core_pin['version']} has no labeled live-pilot evidence; retrying later"
        )
        write_output("changed", "false")
        return

    def tag_exists(tag: str) -> bool:
        return gh_api_optional(f"repos/{args.repository}/git/ref/tags/{tag}") is not None

    new_version = next_add_on_version(previous["add_on"], tag_exists)
    update_from = previous["add_on"] if tag_exists(f"ftw-v{previous['add_on']}") else None
    new_compat, new_config, new_changelog, pilot = compose_updates(
        compat=compat,
        config_text=config_text,
        changelog_text=changelog_text,
        core_pin=core_pin,
        optimizer_pin=optimizer_pin,
        new_version=new_version,
        update_from=update_from,
    )

    (ROOT / "compatibility.yaml").write_text(dump_yaml(new_compat), encoding="utf-8")
    (ROOT / "ftw/config.yaml").write_text(new_config, encoding="utf-8")
    (ROOT / "ftw/CHANGELOG.md").write_text(new_changelog, encoding="utf-8")
    (ROOT / f"pilot/{new_version}.yaml").write_text(dump_yaml(pilot), encoding="utf-8")
    if args.pr_body is not None:
        args.pr_body.write_text(
            render_pr_body(
                previous=previous,
                new_version=new_version,
                compat=new_compat,
                core_pin=core_pin,
                optimizer_pin=optimizer_pin,
            ),
            encoding="utf-8",
        )

    parts = []
    if core_pin is not None:
        parts.append(f"Core {core_pin['version']}")
    if optimizer_pin is not None:
        parts.append(f"Optimizer {optimizer_pin['version']}")
    title = f"chore: pin {' and '.join(parts)} as {new_version}"
    write_output("changed", "true")
    write_output("add_on_version", new_version)
    write_output("branch", f"bot/sync-ftw-{new_version}")
    write_output("pr_title", title)
    print(f"prepared {new_version}: {title}")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    sync_command = commands.add_parser("sync")
    sync_command.add_argument("--repository", required=True)
    sync_command.add_argument("--upstream", default=UPSTREAM_REPOSITORY)
    sync_command.add_argument("--pr-body", type=pathlib.Path, default=None)
    sync_command.set_defaults(handler=sync)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (SyncError, OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"upstream sync failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
