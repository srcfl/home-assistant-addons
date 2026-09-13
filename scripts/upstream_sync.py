#!/usr/bin/env python3
"""Sync the app pins to the newest upstream FTW release of each channel.

Beta: the newest FTW prerelease becomes the `ftw-beta` app version, built from
the exact Core image digest FTW recorded in that release's
`ftw-image-digests.json` receipt.

Stable: the newest FTW stable release becomes the `ftw` app version by
promoting the app beta that was built from the same Core digest, which FTW
names in the release's `ftw-promotion-receipt.json`. Stable is left alone until
compatibility.yaml records a passed Home Assistant OS and Supervisor pilot.

Every pin is checked against the registry (a multi-arch index whose platform
images carry the expected revision and version labels) and against FTW's
receipt. The script never downgrades a channel, never builds or pushes an
image, and leaves publication to the release workflows.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any

import yaml

try:
    from scripts import release_gate
except ImportError:  # `python scripts/upstream_sync.py` puts scripts/ first on sys.path.
    import release_gate  # type: ignore[no-redef]


ROOT = pathlib.Path(__file__).resolve().parents[1]
UPSTREAM_REPOSITORY = "srcfl/ftw"
CORE_IMAGE = "ghcr.io/srcfl/ftw"
BETA_TAG = re.compile(r"^v\d+\.\d+\.\d+-beta\.\d+$")
STABLE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
UPSTREAM_VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
ABSENT_IMAGE_MARKERS = ("manifest unknown", "name unknown", "not found")
RECEIPTS = {"beta": "ftw-image-digests.json", "stable": "ftw-promotion-receipt.json"}
ADD_ON_DIRECTORIES = {"beta": "ftw-beta", "stable": "ftw"}
STABLE_CONFIG_LINES = {
    "name": "name: FTW",
    "description": "description: Local-first home energy control from Sourceful",
    "slug": "slug: ftw",
    "url": "url: https://github.com/srcfl/home-assistant-addons/tree/main/ftw",
}


class SyncError(Exception):
    pass


class ImageNotReady(SyncError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SyncError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


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


def add_on_version(core_version: str) -> str:
    require(UPSTREAM_VERSION.fullmatch(core_version) is not None, f"upstream version is invalid: {core_version}")
    return core_version[1:]


def select_latest_release(releases: list[Any], channel: str) -> dict[str, Any] | None:
    pattern = BETA_TAG if channel == "beta" else STABLE_TAG
    prerelease = channel == "beta"
    best: dict[str, Any] | None = None
    best_key: tuple[int, ...] | None = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = str(release.get("tag_name", ""))
        if pattern.fullmatch(tag) is None or bool(release.get("prerelease")) != prerelease:
            continue
        key = version_key(tag)
        if key is None:
            continue
        if best_key is None or key > best_key:
            best, best_key = release, key
    return best


def download_release_asset(repository: str, tag: str, name: str) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        result = run(["gh", "release", "download", tag, "--repo", repository, "--pattern", name, "--dir", directory])
        path = pathlib.Path(directory) / name
        if result.returncode != 0 or not path.is_file():
            raise ImageNotReady(f"{repository} release {tag} has no {name} asset yet")
        return path.read_bytes()


def parse_receipt(raw: bytes, *, channel: str, tag: str, commit: str) -> dict[str, str]:
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyncError(f"{tag} receipt is not valid JSON: {error}") from error
    require(isinstance(receipt, dict) and receipt.get("schema") == 1, f"{tag} receipt schema is not 1")
    if channel == "beta":
        require(receipt.get("tag") == tag, f"{tag} receipt names a different tag")
        source_beta = tag
    else:
        require(receipt.get("stable_tag") == tag, f"{tag} receipt names a different stable tag")
        source_beta = str(receipt.get("source_beta", ""))
        require(BETA_TAG.fullmatch(source_beta) is not None, f"{tag} receipt names an invalid source beta")
    require(receipt.get("commit") == commit, f"{tag} receipt commit differs from the tag")
    images = receipt.get("images")
    core = images.get("core") if isinstance(images, dict) else None
    digest = str(core.get("digest", "")) if isinstance(core, dict) else ""
    require(DIGEST.fullmatch(digest) is not None, f"{tag} receipt lacks a Core digest")
    return {"digest": digest, "source_beta": source_beta}


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
    """Resolve the release digest and require the labels the release gate re-checks."""
    digest = None
    for tag in dict.fromkeys((version, version.removeprefix("v"))):
        digest = optional_image_digest(f"{image}:{tag}")
        if digest is not None:
            break
    if digest is None:
        raise ImageNotReady(f"{image} has no published image for {version} yet")
    index = json.loads(command_output(["docker", "buildx", "imagetools", "inspect", f"{image}@{digest}", "--raw"]))
    require(isinstance(index, dict), f"{image} pin must resolve to a multi-arch index")
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
            f"{image} linux/{architecture} OCI version label does not match {version}",
        )
        require(
            labels.get("org.opencontainers.image.revision") == expected_commit,
            f"{image} linux/{architecture} OCI revision label does not match {expected_commit}",
        )
    return digest


def resolve_core_pin(
    *,
    upstream: str,
    release: dict[str, Any],
    channel: str,
    current_version: str,
) -> dict[str, Any] | None:
    tag = str(release.get("tag_name", ""))
    if tag == current_version:
        return None
    new_key = version_key(tag)
    require(new_key is not None, f"upstream release tag is invalid: {tag}")
    current_key = version_key(current_version) if current_version else None
    if current_key is not None and new_key <= current_key:
        return None
    commit = str(gh_api(f"repos/{upstream}/commits/{tag}").get("sha", ""))
    require(COMMIT.fullmatch(commit) is not None, f"could not resolve the commit for {tag}")
    receipt = parse_receipt(
        download_release_asset(upstream, tag, RECEIPTS[channel]),
        channel=channel,
        tag=tag,
        commit=commit,
    )
    digest = inspect_release_image(CORE_IMAGE, tag, commit)
    require(
        digest == receipt["digest"],
        f"{CORE_IMAGE}:{tag} resolves to {digest}, but FTW's release receipt records {receipt['digest']}",
    )
    return {
        "version": tag,
        "commit": commit,
        "digest": digest,
        "release_url": str(release.get("html_url", "")),
        "source_beta": receipt["source_beta"],
    }


def current_driver_baseline(drivers: dict[str, Any]) -> dict[str, Any]:
    """Record the signed stable driver manifest as it is at pin time."""
    key_id = str(drivers.get("tested_baseline", {}).get("key_id", release_gate.DRIVER_KEY_ID))
    raw = release_gate.download_driver_manifest(str(drivers.get("manifest", "")))
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyncError(f"driver manifest is not valid JSON: {error}") from error
    payload = envelope.get("payload") if isinstance(envelope, dict) else None
    commit = str(payload.get("commit", "")) if isinstance(payload, dict) else ""
    require(COMMIT.fullmatch(commit) is not None, "driver manifest payload lacks a source commit")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        release_gate.validate_signed_driver_manifest(
            raw,
            expected_sha256=digest,
            expected_commit=commit,
            expected_key_id=key_id,
        )
    except release_gate.GateError as error:
        raise SyncError(f"driver manifest verification failed: {error}") from error
    return {
        "commit": commit,
        "manifest_sha256": digest,
        "key_id": key_id,
        "evidence": {
            "commit": f"https://github.com/srcfl/device-drivers/commit/{commit}",
            "release": "https://github.com/srcfl/device-drivers/releases/tag/drivers-stable",
        },
    }


def replace_line(text: str, pattern: str, replacement: str, name: str) -> str:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    require(len(matches) == 1, f"config.yaml must contain exactly one {name} line")
    return re.sub(pattern, replacement, text, count=1, flags=re.MULTILINE)


def replace_config_version(text: str, version: str, core_version: str) -> str:
    text = replace_line(text, r'^version: "[^"\n]*"$', f'version: "{version}"', "version")
    text = replace_line(
        text,
        r'^  FTW_BUNDLE_VERSION: "[^"\n]*"$',
        f'  FTW_BUNDLE_VERSION: "{version}"',
        "FTW_BUNDLE_VERSION",
    )
    return replace_line(text, r"^  FTW_IMAGE_TAG: [^\n]*$", f"  FTW_IMAGE_TAG: {core_version}", "FTW_IMAGE_TAG")


def render_stable_config(beta_text: str, version: str, core_version: str) -> str:
    """Derive ftw/config.yaml from the beta manifest: same contract, stable identity."""
    text = beta_text
    for key, line in STABLE_CONFIG_LINES.items():
        text = replace_line(text, rf"^{key}: [^\n]*$", line, key)
    matches = re.findall(r"^stage: [^\n]*\n", text, flags=re.MULTILINE)
    require(len(matches) == 1, "beta config.yaml must contain exactly one stage line")
    text = re.sub(r"^stage: [^\n]*\n", "", text, count=1, flags=re.MULTILINE)
    return replace_config_version(text, version, core_version)


def prepend_changelog(text: str, version: str, lines: list[str]) -> str:
    header = "# Changelog\n"
    require(text.startswith(header), "CHANGELOG.md must start with the changelog header")
    body = text[len(header):].lstrip("\n")
    entry = f"## {version}\n\n" + "".join(f"- {line}\n" for line in lines)
    return f"{header}\n{entry}\n{body}" if body else f"{header}\n{entry}"


def compose_beta_update(
    *,
    compat: dict[str, Any],
    config_text: str,
    changelog_text: str,
    pin: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    version = add_on_version(pin["version"])
    updated = copy.deepcopy(compat)
    updated["beta"] = {
        "add_on": ADD_ON_DIRECTORIES["beta"],
        "version": version,
        "core": {
            "version": pin["version"],
            "commit": pin["commit"],
            "digest": pin["digest"],
            "release": pin["release_url"],
        },
    }
    updated["drivers"]["tested_baseline"] = copy.deepcopy(baseline)
    config = replace_config_version(config_text, version, pin["version"])
    changelog = prepend_changelog(
        changelog_text,
        version,
        [
            f"Update Core to {pin['version']} (`{pin['digest']}`).",
            f"Record the stable driver baseline `{baseline['commit'][:12]}`.",
        ],
    )
    return updated, config, changelog


def add_on_beta_release(repository: str, version: str) -> dict[str, Any] | None:
    tag = f"ftw-v{version}"
    if gh_api_optional(f"repos/{repository}/releases/tags/{tag}") is None:
        return None
    try:
        manifest = json.loads(download_release_asset(repository, tag, "release-manifest.json"))
    except ImageNotReady as error:
        raise SyncError(f"{tag} exists without a release manifest: {error}") from error
    require(isinstance(manifest, dict), f"{tag} release manifest is invalid")
    require(manifest.get("channel") == "beta", f"{tag} release manifest is not a beta record")
    require(manifest.get("version") == version, f"{tag} release manifest names a different version")
    require(DIGEST.fullmatch(str(manifest.get("manifest_digest", ""))) is not None, f"{tag} manifest digest is invalid")
    require(COMMIT.fullmatch(str(manifest.get("source_commit", ""))) is not None, f"{tag} source commit is invalid")
    core = manifest.get("core")
    require(isinstance(core, dict) and DIGEST.fullmatch(str(core.get("digest", ""))) is not None, f"{tag} lacks a Core digest")
    return manifest


def compose_stable_update(
    *,
    compat: dict[str, Any],
    beta_config_text: str,
    changelog_text: str,
    pin: dict[str, Any],
    add_on_beta: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    version = add_on_version(pin["version"])
    beta_version = add_on_version(pin["source_beta"])
    require(
        add_on_beta.get("version") == beta_version,
        f"FTW {pin['version']} was promoted from {pin['source_beta']}, not app beta {add_on_beta.get('version')}",
    )
    require(
        add_on_beta["core"]["digest"] == pin["digest"],
        f"app beta {beta_version} was built from Core {add_on_beta['core']['digest']}, but FTW promoted {pin['digest']}",
    )
    updated = copy.deepcopy(compat)
    updated["stable"] = {
        "add_on": ADD_ON_DIRECTORIES["stable"],
        "version": version,
        "promoted_from_beta": beta_version,
        "manifest_digest": add_on_beta["manifest_digest"],
        "source_commit": add_on_beta["source_commit"],
        "core": {
            "version": pin["version"],
            "commit": pin["commit"],
            "digest": pin["digest"],
            "release": pin["release_url"],
        },
    }
    config = render_stable_config(beta_config_text, version, pin["version"])
    changelog = prepend_changelog(
        changelog_text,
        version,
        [
            f"Promote app beta {beta_version} (Core {pin['version']}, `{pin['digest']}`) to stable.",
            "The image is the tested beta manifest re-tagged; nothing was rebuilt.",
        ],
    )
    return updated, config, changelog


class IndentedDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)


def dump_yaml(value: dict[str, Any]) -> str:
    return yaml.dump(value, Dumper=IndentedDumper, sort_keys=False, allow_unicode=True, width=120)


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with pathlib.Path(output).open("a", encoding="utf-8") as target:
            target.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def plan(
    *,
    repository: str,
    upstream: str,
    compat: dict[str, Any],
    beta_config_text: str,
    beta_changelog_text: str,
    stable_changelog_text: str,
    releases: list[Any],
) -> dict[str, Any]:
    """Decide what changes; touches the network only through the helpers above."""
    result: dict[str, Any] = {"compat": compat, "files": {}, "changed": [], "pins": {}}
    beta_release = select_latest_release(releases, "beta")
    stable_release = select_latest_release(releases, "stable")
    require(beta_release is not None, "no Core beta release was found upstream")

    try:
        beta_pin = resolve_core_pin(
            upstream=upstream,
            release=beta_release,
            channel="beta",
            current_version=str(compat["beta"]["core"]["version"]),
        )
    except ImageNotReady as error:
        print(f"::notice::upstream beta is not ready yet, retrying later: {error}")
        beta_pin = None
    if beta_pin is not None:
        baseline = current_driver_baseline(compat["drivers"])
        compat, config, changelog = compose_beta_update(
            compat=compat,
            config_text=beta_config_text,
            changelog_text=beta_changelog_text,
            pin=beta_pin,
            baseline=baseline,
        )
        result["files"]["ftw-beta/config.yaml"] = config
        result["files"]["ftw-beta/CHANGELOG.md"] = changelog
        result["changed"].append("beta")
        result["pins"]["beta"] = beta_pin

    pilot = compat["qualification"]["home_assistant_os_supervisor"]
    if stable_release is not None and pilot.get("status") != "passed":
        print(
            "::notice::stable channel is blocked until compatibility.yaml records a passed "
            f"Home Assistant OS and Supervisor pilot; not promoting {stable_release.get('tag_name')}"
        )
    elif stable_release is not None:
        current = compat["stable"].get("core") or {}
        try:
            stable_pin = resolve_core_pin(
                upstream=upstream,
                release=stable_release,
                channel="stable",
                current_version=str(current.get("version") or ""),
            )
        except ImageNotReady as error:
            print(f"::notice::upstream stable is not ready yet, retrying later: {error}")
            stable_pin = None
        if stable_pin is not None:
            beta_version = add_on_version(stable_pin["source_beta"])
            record = add_on_beta_release(repository, beta_version)
            if record is None:
                print(
                    f"::notice::FTW {stable_pin['version']} was promoted from {stable_pin['source_beta']}, "
                    f"but app beta {beta_version} is not published yet; retrying later"
                )
            else:
                compat, config, changelog = compose_stable_update(
                    compat=compat,
                    beta_config_text=beta_config_text,
                    changelog_text=stable_changelog_text,
                    pin=stable_pin,
                    add_on_beta=record,
                )
                result["files"]["ftw/config.yaml"] = config
                result["files"]["ftw/CHANGELOG.md"] = changelog
                result["changed"].append("stable")
                result["pins"]["stable"] = stable_pin

    result["compat"] = compat
    return result


def render_pr_body(previous: dict[str, Any], planned: dict[str, Any]) -> str:
    lines = ["| Channel | App | Before | After | Core |", "|---|---|---|---|---|"]
    for channel in planned["changed"]:
        pin = planned["pins"][channel]
        before = previous[channel].get("version") or "none"
        after = planned["compat"][channel]["version"]
        lines.append(
            f"| {channel} | `{ADD_ON_DIRECTORIES[channel]}` | `{before}` | `{after}` | "
            f"[{pin['version']}]({pin['release_url']}) |"
        )
    details = []
    for channel in planned["changed"]:
        pin = planned["pins"][channel]
        details.append(f"- {channel}: commit `{pin['commit']}`, Core digest `{pin['digest']}`")
        if channel == "stable":
            stable = planned["compat"]["stable"]
            details.append(
                f"  promoted from app beta `{stable['promoted_from_beta']}` at `{stable['manifest_digest']}`"
            )
    baseline = planned["compat"]["drivers"]["tested_baseline"]
    return (
        "Automated pin from the upstream sync workflow.\n\n"
        + "\n".join(lines)
        + "\n\n"
        + "\n".join(details)
        + f"\n- stable driver baseline `{baseline['commit']}` (manifest SHA-256 `{baseline['manifest_sha256']}`)\n\n"
        "Merging publishes through Auto publish. Beta builds from the Core digest; stable re-tags the beta digest.\n"
    )


def sync(args: argparse.Namespace) -> None:
    compat = load_yaml(ROOT / "compatibility.yaml")
    previous = copy.deepcopy(compat)
    releases = gh_api(f"repos/{args.upstream}/releases?per_page=100")
    require(isinstance(releases, list), "upstream releases response is invalid")
    stable_changelog = ROOT / "ftw/CHANGELOG.md"
    planned = plan(
        repository=args.repository,
        upstream=args.upstream,
        compat=compat,
        beta_config_text=(ROOT / "ftw-beta/config.yaml").read_text(encoding="utf-8"),
        beta_changelog_text=(ROOT / "ftw-beta/CHANGELOG.md").read_text(encoding="utf-8"),
        stable_changelog_text=(
            stable_changelog.read_text(encoding="utf-8") if stable_changelog.is_file() else "# Changelog\n"
        ),
        releases=releases,
    )
    if not planned["changed"]:
        print("pins already match the latest upstream releases")
        write_output("changed", "false")
        return

    (ROOT / "compatibility.yaml").write_text(dump_yaml(planned["compat"]), encoding="utf-8")
    for name, text in planned["files"].items():
        (ROOT / name).write_text(text, encoding="utf-8")
    if args.pr_body is not None:
        args.pr_body.write_text(render_pr_body(previous, planned), encoding="utf-8")

    parts = [
        f"{ADD_ON_DIRECTORIES[channel]} {planned['compat'][channel]['version']} "
        f"from Core {planned['pins'][channel]['version']}"
        for channel in planned["changed"]
    ]
    versions = "-".join(planned["compat"][channel]["version"] for channel in planned["changed"])
    write_output("changed", "true")
    write_output("branch", f"bot/sync-ftw-{versions}")
    write_output("pr_title", f"chore: pin {' and '.join(parts)}")
    print(f"prepared {', '.join(planned['changed'])}: {' and '.join(parts)}")


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
