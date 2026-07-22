#!/usr/bin/env python3
"""Fail-closed checks for beta publication and stable promotion."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any, Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = pathlib.Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
ABSENT_IMAGE_MARKERS = ("manifest unknown", "name unknown", "not found")
DRIVER_KEY_ID = "ftw-drivers-2026-01"
DRIVER_PUBLIC_KEY = "MX+j27UBkyM099hTyJlmMLK9qlTTDUJsaK/vH12fFKc="
DRIVER_REPOSITORY = "https://github.com/srcfl/device-drivers"
MAX_DRIVER_MANIFEST_BYTES = 2 << 20


class GateError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def load_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def command_output(command: list[str]) -> str:
    result = run(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GateError(f"command failed ({' '.join(command)}): {detail}")
    return result.stdout.strip()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def download_driver_manifest(url: str) -> bytes:
    require(url.startswith("https://"), "driver manifest URL must use HTTPS")
    request = Request(url, headers={"User-Agent": "srcfl-home-assistant-addons-release-gate"})
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(MAX_DRIVER_MANIFEST_BYTES + 1)
    except (OSError, URLError) as exc:
        raise GateError(f"could not download driver manifest: {exc}") from exc
    require(raw, "downloaded driver manifest is empty")
    require(len(raw) <= MAX_DRIVER_MANIFEST_BYTES, "driver manifest exceeds the size limit")
    return raw


def validate_signed_driver_manifest(
    raw: bytes,
    *,
    expected_sha256: str,
    expected_commit: str,
    expected_key_id: str = DRIVER_KEY_ID,
    public_key_base64: str = DRIVER_PUBLIC_KEY,
) -> dict[str, Any]:
    require(
        re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
        "driver manifest SHA-256 is invalid",
    )
    require(COMMIT.fullmatch(expected_commit) is not None, "driver baseline commit is invalid")
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, "driver manifest SHA-256 mismatch")
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"driver manifest is not valid JSON: {exc}") from exc
    require(isinstance(envelope, dict), "driver manifest envelope must be an object")
    require(raw == canonical_json(envelope) + b"\n", "driver manifest must use exact canonical JSON bytes")
    require(envelope.get("schema_version") == 1, "driver manifest schema_version must be 1")
    require(envelope.get("key_id") == expected_key_id, "driver manifest key id mismatch")
    payload = envelope.get("payload")
    signature_value = envelope.get("signature")
    require(isinstance(payload, dict), "driver manifest payload must be an object")
    require(isinstance(signature_value, str), "driver manifest signature is missing")
    try:
        signature = base64.b64decode(signature_value, validate=True)
        public_key = base64.b64decode(public_key_base64, validate=True)
    except ValueError as exc:
        raise GateError("driver manifest signature or public key is not valid base64") from exc
    require(len(public_key) == 32, "driver manifest public key must be 32 bytes")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, canonical_json(payload))
    except InvalidSignature as exc:
        raise GateError("driver manifest signature verification failed") from exc

    require(payload.get("schema_version") == 1, "driver manifest payload schema_version must be 1")
    require(payload.get("repository") == DRIVER_REPOSITORY, "driver manifest payload repository is wrong")
    require(payload.get("commit") == expected_commit, "driver manifest payload commit mismatch")
    drivers = payload.get("drivers")
    require(isinstance(drivers, list) and drivers, "driver manifest payload lacks drivers")
    for driver in drivers:
        require(isinstance(driver, dict), "driver manifest entry must be an object")
        require(
            driver.get("channel") == "stable",
            "driver manifest contains a non-stable current driver",
        )
        require(
            driver.get("source_commit") == expected_commit,
            "driver manifest driver source commit mismatch",
        )
    return payload


def verify_current_driver_baseline(drivers: dict[str, Any]) -> None:
    baseline = drivers.get("tested_baseline")
    require(isinstance(baseline, dict), "tested driver baseline is missing")
    require(baseline.get("key_id") == DRIVER_KEY_ID, "tested driver key id mismatch")
    raw = download_driver_manifest(str(drivers.get("manifest", "")))
    validate_signed_driver_manifest(
        raw,
        expected_sha256=str(baseline.get("manifest_sha256", "")),
        expected_commit=str(baseline.get("commit", "")),
        expected_key_id=str(baseline.get("key_id", "")),
    )


def validate_beta_target_state(*, git_tag_exists: bool, release_exists: bool, image_digest: str | None) -> None:
    require(not git_tag_exists, "beta Git tag already exists")
    require(not release_exists, "beta GitHub release already exists")
    require(image_digest is None, "immutable beta image version tag already exists")


def validate_workflow_source(*, ref: str, expected_sha: str, actual_sha: str) -> None:
    require(ref == "refs/heads/main", "release workflows must run from refs/heads/main")
    require(COMMIT.fullmatch(expected_sha) is not None, "github.sha is invalid")
    require(actual_sha == expected_sha, "checked-out HEAD differs from github.sha")


def optional_image_digest(reference: str) -> str | None:
    result = run(["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"])
    if result.returncode == 0:
        digest = result.stdout.strip()
        require(DIGEST.fullmatch(digest) is not None, f"registry returned an invalid digest for {reference}")
        return digest
    detail = f"{result.stdout}\n{result.stderr}".lower()
    if any(marker in detail for marker in ABSENT_IMAGE_MARKERS):
        return None
    raise GateError(f"could not check image tag {reference}: {(result.stderr or result.stdout).strip()}")


def beta_target_state(repository: str, image: str, version: str) -> None:
    tag = f"ftw-v{version}"
    git_result = run(["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"])
    if git_result.returncode not in (0, 2):
        raise GateError(f"could not check Git tag {tag}: {(git_result.stderr or git_result.stdout).strip()}")

    release_result = run(["gh", "release", "view", tag, "--repo", repository, "--json", "tagName"])
    if release_result.returncode == 0:
        release_exists = True
    else:
        detail = f"{release_result.stdout}\n{release_result.stderr}".lower()
        require("release not found" in detail, f"could not check GitHub release {tag}: {detail.strip()}")
        release_exists = False

    validate_beta_target_state(
        git_tag_exists=git_result.returncode == 0,
        release_exists=release_exists,
        image_digest=optional_image_digest(f"{image}:{version}"),
    )


def image_labels(image: dict[str, Any]) -> dict[str, str]:
    config = image.get("config") or image.get("Config")
    require(isinstance(config, dict), "image config is missing")
    labels = config.get("Labels") or config.get("labels")
    require(isinstance(labels, dict), "image labels are missing")
    return {str(key): str(value) for key, value in labels.items()}


def validate_image_platforms(
    *,
    name: str,
    index: dict[str, Any],
    platform_images: dict[str, dict[str, Any]],
    expected_version: str,
    expected_commit: str,
    required_architectures: Iterable[str] = ("amd64", "arm64"),
) -> None:
    manifests = index.get("manifests")
    require(isinstance(manifests, list), f"{name} pin must resolve to a multi-arch index")
    found: dict[str, str] = {}
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        platform = manifest.get("platform")
        if not isinstance(platform, dict) or platform.get("os") != "linux":
            continue
        architecture = platform.get("architecture")
        digest = manifest.get("digest")
        if architecture in required_architectures and isinstance(digest, str):
            found[str(architecture)] = digest

    for architecture in required_architectures:
        require(architecture in found, f"{name} image lacks linux/{architecture}")
        image = platform_images.get(architecture)
        require(isinstance(image, dict), f"{name} linux/{architecture} config is missing")
        labels = image_labels(image)
        require(
            labels.get("org.opencontainers.image.version") == expected_version,
            f"{name} linux/{architecture} OCI version label does not match compatibility.yaml",
        )
        require(
            labels.get("org.opencontainers.image.revision") == expected_commit,
            f"{name} linux/{architecture} OCI revision label does not match compatibility.yaml",
        )


def inspect_pinned_image(name: str, image: str, digest: str, version: str, commit: str) -> None:
    require(DIGEST.fullmatch(digest) is not None, f"{name} digest is invalid")
    require(COMMIT.fullmatch(commit) is not None, f"{name} commit is invalid")
    reference = f"{image}@{digest}"
    actual = command_output(
        ["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"]
    )
    require(actual == digest, f"{name} registry digest does not match compatibility.yaml")
    index = json.loads(command_output(["docker", "buildx", "imagetools", "inspect", reference, "--raw"]))
    require(isinstance(index, dict), f"{name} registry index is invalid")

    manifests = index.get("manifests", [])
    platform_images: dict[str, dict[str, Any]] = {}
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
        require(isinstance(descriptor, dict), f"{name} image lacks linux/{architecture}")
        child_digest = descriptor.get("digest")
        require(isinstance(child_digest, str), f"{name} linux/{architecture} digest is missing")
        child = command_output(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                f"{image}@{child_digest}",
                "--format",
                "{{json .Image}}",
            ]
        )
        parsed = json.loads(child)
        require(isinstance(parsed, dict), f"{name} linux/{architecture} config is invalid")
        platform_images[architecture] = parsed

    validate_image_platforms(
        name=name,
        index=index,
        platform_images=platform_images,
        expected_version=version,
        expected_commit=commit,
    )


def validate_stable_tag(existing_digest: str | None, expected_digest: str) -> bool:
    require(
        existing_digest is None or existing_digest == expected_digest,
        "stable version tag exists with a different digest",
    )
    return existing_digest is not None


def validate_beta_release_record(
    *,
    manifest: dict[str, Any],
    compatibility: dict[str, Any],
    beta_version: str,
    beta_digest: str,
) -> tuple[str, str]:
    promoted = compatibility.get("qualification", {}).get("promoted_from_beta", {})
    require(isinstance(promoted, dict), "compatibility promoted beta record is missing")
    expected = {
        "channel": promoted.get("channel"),
        "version": promoted.get("version"),
        "manifest_digest": promoted.get("manifest_digest"),
        "source_commit": promoted.get("source_commit"),
    }
    requested = {
        "channel": "beta",
        "version": beta_version,
        "manifest_digest": beta_digest,
        "source_commit": expected["source_commit"],
    }
    for field, value in requested.items():
        require(expected[field] == value, f"compatibility promoted beta {field} mismatch")
        require(manifest.get(field) == value, f"beta release manifest {field} mismatch")

    require(
        compatibility.get("add_on", {}).get("manifest_digest") == beta_digest,
        "stable compatibility digest differs from beta",
    )
    source_commit = str(expected["source_commit"])
    require(COMMIT.fullmatch(source_commit) is not None, "promoted beta source commit is invalid")
    image = manifest.get("image")
    require(isinstance(image, str) and image == compatibility.get("add_on", {}).get("image"), "beta image mismatch")
    return image, source_commit


def write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with pathlib.Path(output).open("a", encoding="utf-8") as target:
            target.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def beta_prepare(args: argparse.Namespace) -> None:
    compat = load_yaml(ROOT / "compatibility.yaml")
    beta_target_state(args.repository, compat["add_on"]["image"], args.version)
    verify_current_driver_baseline(compat["drivers"])
    for key, name in (("core", "Core"), ("optimizer", "Optimizer")):
        item = compat[key]
        inspect_pinned_image(name, item["image"], item["digest"], item["version"], item["commit"])


def source_prepare(args: argparse.Namespace) -> None:
    actual_sha = command_output(["git", "rev-parse", "HEAD"])
    validate_workflow_source(ref=args.ref, expected_sha=args.sha, actual_sha=actual_sha)


def stable_prepare(args: argparse.Namespace) -> None:
    config = load_yaml(ROOT / "ftw/config.yaml")
    compat = load_yaml(ROOT / "compatibility.yaml")
    require(config.get("version") == args.version, "stable workflow version differs from config.yaml")
    manifest = load_json(args.release_manifest)
    image, source_commit = validate_beta_release_record(
        manifest=manifest,
        compatibility=compat,
        beta_version=args.beta_version,
        beta_digest=args.beta_digest,
    )
    inspect_pinned_image("Beta add-on", image, args.beta_digest, args.beta_version, source_commit)
    exists = validate_stable_tag(optional_image_digest(f"{image}:{args.version}"), args.beta_digest)
    write_output("beta_source_commit", source_commit)
    write_output("stable_tag_exists", str(exists).lower())


def compare_json(args: argparse.Namespace) -> None:
    validate_same_json(load_json(args.expected), load_json(args.actual))


def validate_same_json(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    require(expected == actual, "existing release manifest differs from this run")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    source = commands.add_parser("source-prepare")
    source.add_argument("--ref", required=True)
    source.add_argument("--sha", required=True)
    source.set_defaults(handler=source_prepare)

    beta = commands.add_parser("beta-prepare")
    beta.add_argument("--version", required=True)
    beta.add_argument("--repository", required=True)
    beta.set_defaults(handler=beta_prepare)

    stable = commands.add_parser("stable-prepare")
    stable.add_argument("--version", required=True)
    stable.add_argument("--beta-version", required=True)
    stable.add_argument("--beta-digest", required=True)
    stable.add_argument("--release-manifest", type=pathlib.Path, required=True)
    stable.set_defaults(handler=stable_prepare)

    compare = commands.add_parser("compare-json")
    compare.add_argument("--expected", type=pathlib.Path, required=True)
    compare.add_argument("--actual", type=pathlib.Path, required=True)
    compare.set_defaults(handler=compare_json)

    args = parser.parse_args()
    try:
        args.handler(args)
    except (GateError, OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"release gate failed: {error}", file=sys.stderr)
        return 1
    print("release gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
