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
import tempfile
from typing import Any, Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_IMAGE = "ghcr.io/srcfl/ftw"
CORE_VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
ABSENT_IMAGE_MARKERS = ("manifest unknown", "name unknown", "not found")
DRIVER_KEY_ID = "ftw-drivers-2026-01"
DRIVER_PUBLIC_KEY = "MX+j27UBkyM099hTyJlmMLK9qlTTDUJsaK/vH12fFKc="
DRIVER_REPOSITORY = "https://github.com/srcfl/device-drivers"
MAX_DRIVER_MANIFEST_BYTES = 2 << 20
SBOM_PREDICATE_TYPE = "https://spdx.dev/Document/v2.3"
RELEASE_WORKFLOW_PATH = ".github/workflows/release-beta.yml"
RELEASE_WORKFLOW_IDENTITY = (
    "https://github.com/srcfl/home-assistant-addons/"
    ".github/workflows/release-beta.yml@refs/heads/main"
)
FINALIZE_WORKFLOW_IDENTITY = (
    "https://github.com/srcfl/home-assistant-addons/"
    ".github/workflows/finalize-beta.yml@refs/heads/main"
)
RESUME_JOB_RESULTS = {
    "Validate release inputs": "success",
    "Build and sign amd64": "success",
    "Build and sign aarch64": "success",
    "Publish and sign multi-arch beta": "success",
    "Record digest, SBOM, and attestation": "failure",
}
RESUME_CRITICAL_PATHS = (
    "compatibility.yaml",
    "ftw/config.yaml",
    "ftw/Dockerfile",
    "ftw/run.sh",
    "ftw/healthcheck.py",
)
ADD_ON_ARCHITECTURES = {"amd64": "amd64", "aarch64": "arm64"}


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


def parse_yaml(value: str, name: str) -> dict[str, Any]:
    parsed = yaml.safe_load(value)
    require(isinstance(parsed, dict), f"{name} must contain an object")
    return parsed


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


def validate_beta_resume_target_state(
    *,
    git_tag_exists: bool,
    release_exists: bool,
    version_digest: str | None,
    beta_digest: str | None,
    expected_digest: str,
) -> None:
    require(DIGEST.fullmatch(expected_digest) is not None, "resume digest is invalid")
    require(not git_tag_exists, "resume beta Git tag already exists")
    require(not release_exists, "resume beta GitHub release already exists")
    require(version_digest is not None, "resume image version tag is missing")
    require(version_digest == expected_digest, "resume image version tag digest mismatch")
    require(beta_digest is not None, "resume beta alias is missing")
    require(beta_digest == expected_digest, "resume beta alias digest mismatch")


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


def validate_pinned_version_tag(name: str, image: str, version: str, expected_digest: str) -> None:
    actual_digest = None
    for tag in dict.fromkeys((version, version.removeprefix("v"))):
        actual_digest = optional_image_digest(f"{image}:{tag}")
        if actual_digest is not None:
            break
    require(actual_digest is not None, f"{name} image tag for {version} is missing")
    require(actual_digest == expected_digest, f"{name} image tag for {version} has the wrong digest")


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


def release_target_state(repository: str, image: str, version: str, expected_digest: str) -> None:
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

    validate_beta_resume_target_state(
        git_tag_exists=git_result.returncode == 0,
        release_exists=release_exists,
        version_digest=optional_image_digest(f"{image}:{version}"),
        beta_digest=optional_image_digest(f"{image}:beta"),
        expected_digest=expected_digest,
    )


def image_labels(image: dict[str, Any]) -> dict[str, str]:
    config = image.get("config") or image.get("Config")
    require(isinstance(config, dict), "image config is missing")
    labels = config.get("Labels") or config.get("labels")
    require(isinstance(labels, dict), "image labels are missing")
    return {str(key): str(value) for key, value in labels.items()}


def allowed_oci_version_labels(image: str, release_version: str) -> set[str]:
    if image != CORE_IMAGE:
        return {release_version}
    match = CORE_VERSION.fullmatch(release_version)
    require(match is not None, f"Core release version is invalid: {release_version}")
    major, minor, patch, beta = match.groups()
    package_version = f"{major}.{minor}.{patch}"
    if beta is None:
        return {package_version}
    return {release_version, package_version}


def validate_image_platforms(
    *,
    name: str,
    image_repository: str,
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
        platform_image = platform_images.get(architecture)
        require(isinstance(platform_image, dict), f"{name} linux/{architecture} config is missing")
        labels = image_labels(platform_image)
        require(
            labels.get("org.opencontainers.image.version")
            in allowed_oci_version_labels(image_repository, expected_version),
            f"{name} linux/{architecture} OCI version label does not match compatibility.yaml",
        )
        require(
            labels.get("org.opencontainers.image.revision") == expected_commit,
            f"{name} linux/{architecture} OCI revision label does not match compatibility.yaml",
        )


def inspect_pinned_image(name: str, image: str, digest: str, version: str, commit: str) -> None:
    require(DIGEST.fullmatch(digest) is not None, f"{name} digest is invalid")
    require(COMMIT.fullmatch(commit) is not None, f"{name} commit is invalid")
    validate_pinned_version_tag(name, image, version, digest)
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
        image_repository=image,
        index=index,
        platform_images=platform_images,
        expected_version=version,
        expected_commit=commit,
    )


def validate_resume_run(
    *,
    run_record: dict[str, Any],
    jobs: list[dict[str, Any]],
    requested_version: str,
    expected_version: str,
    expected_source_commit: str,
) -> None:
    require(run_record.get("status") == "completed", "source workflow run is not complete")
    require(run_record.get("conclusion") == "failure", "source workflow run did not fail")
    require(run_record.get("event") == "workflow_dispatch", "source workflow event mismatch")
    require(run_record.get("head_branch") == "main", "source workflow branch mismatch")
    require(run_record.get("head_sha") == expected_source_commit, "source workflow commit mismatch")
    require(run_record.get("path") == RELEASE_WORKFLOW_PATH, "source workflow path mismatch")
    require(requested_version == expected_version, "source workflow version input mismatch")
    inputs = run_record.get("inputs")
    if inputs is not None:
        require(isinstance(inputs, dict), "source workflow inputs are invalid")
        require(inputs.get("version") == expected_version, "source workflow API version input mismatch")

    for name, conclusion in RESUME_JOB_RESULTS.items():
        matches = [job for job in jobs if isinstance(job, dict) and job.get("name") == name]
        require(len(matches) == 1, f"source workflow must contain one {name} job")
        require(matches[0].get("status") == "completed", f"source workflow job {name} is incomplete")
        require(
            matches[0].get("conclusion") == conclusion,
            f"source workflow job {name} conclusion mismatch",
        )


def requested_version_from_log(log: str) -> str:
    versions = set(re.findall(r"REQUESTED_VERSION:\s*([^\s]+)", log))
    require(len(versions) == 1, "source workflow version input is missing or ambiguous in prepare log")
    return versions.pop()


def validate_resume_source(source_commit: str, version: str) -> dict[str, Any]:
    require(COMMIT.fullmatch(source_commit) is not None, "resume source commit is invalid")
    current_commit = command_output(["git", "rev-parse", "HEAD"])
    ancestor = run(["git", "merge-base", "--is-ancestor", source_commit, current_commit])
    if ancestor.returncode == 1:
        raise GateError("resume source commit is not an ancestor of current main")
    if ancestor.returncode != 0:
        raise GateError(f"could not check resume source ancestry: {(ancestor.stderr or ancestor.stdout).strip()}")

    source_compatibility = parse_yaml(
        command_output(["git", "show", f"{source_commit}:compatibility.yaml"]),
        "source compatibility.yaml",
    )
    source_config = parse_yaml(
        command_output(["git", "show", f"{source_commit}:ftw/config.yaml"]),
        "source ftw/config.yaml",
    )
    require(source_config.get("version") == version, "source app version mismatch")
    require(
        source_compatibility.get("add_on", {}).get("version") == version,
        "source compatibility version mismatch",
    )

    current_compatibility = load_yaml(ROOT / "compatibility.yaml")
    current_config = load_yaml(ROOT / "ftw/config.yaml")
    require(current_config == source_config, "current config.yaml differs from source commit")
    require(
        current_compatibility == source_compatibility,
        "current compatibility.yaml differs from source commit",
    )

    record = source_compatibility.get("qualification", {}).get("home_assistant_os_supervisor", {}).get("record")
    require(isinstance(record, str) and record.startswith("pilot/"), "source pilot record path is invalid")
    critical_paths = (*RESUME_CRITICAL_PATHS, record)
    for path in critical_paths:
        result = run(["git", "diff", "--quiet", source_commit, "--", path])
        if result.returncode == 1:
            raise GateError(f"release-critical file differs from source commit: {path}")
        if result.returncode != 0:
            raise GateError(f"could not compare release-critical file {path}: {(result.stderr or result.stdout).strip()}")
    return source_compatibility


def source_run_evidence(repository: str, run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    require(re.fullmatch(r"[1-9][0-9]*", run_id) is not None, "source run id is invalid")
    run_record = json.loads(command_output(["gh", "api", f"repos/{repository}/actions/runs/{run_id}"]))
    require(isinstance(run_record, dict), "source workflow record is invalid")
    jobs_record = json.loads(
        command_output(["gh", "api", f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"])
    )
    require(isinstance(jobs_record, dict), "source workflow jobs record is invalid")
    jobs = jobs_record.get("jobs")
    require(isinstance(jobs, list), "source workflow jobs are missing")
    prepare_jobs = [job for job in jobs if isinstance(job, dict) and job.get("name") == "Validate release inputs"]
    require(len(prepare_jobs) == 1, "source workflow prepare job is missing")
    prepare_id = prepare_jobs[0].get("id")
    require(isinstance(prepare_id, int), "source workflow prepare job id is missing")
    log = command_output(
        ["gh", "run", "view", run_id, "--repo", repository, "--job", str(prepare_id), "--log"]
    )
    return run_record, jobs, requested_version_from_log(log)


def runtime_descriptors(
    index: dict[str, Any],
    name: str,
    required_architectures: Iterable[str] = ("amd64", "arm64"),
) -> dict[str, dict[str, Any]]:
    manifests = index.get("manifests")
    require(isinstance(manifests, list), f"{name} must resolve to an OCI index")
    required = set(required_architectures)
    found: dict[str, dict[str, Any]] = {}
    unexpected: list[str] = []
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        platform = manifest.get("platform")
        if not isinstance(platform, dict) or platform.get("os") != "linux":
            continue
        architecture = platform.get("architecture")
        if architecture in required:
            require(architecture not in found, f"{name} has duplicate linux/{architecture}")
            require(DIGEST.fullmatch(str(manifest.get("digest", ""))) is not None, f"{name} linux/{architecture} digest is invalid")
            found[str(architecture)] = manifest
        elif architecture != "unknown":
            unexpected.append(str(architecture))
    require(not unexpected, f"{name} has unsupported Linux architectures: {', '.join(unexpected)}")
    require(set(found) == required, f"{name} lacks required Linux architectures")
    return found


def attestation_descriptor_digests(index: dict[str, Any], name: str) -> set[str]:
    manifests = index.get("manifests")
    require(isinstance(manifests, list), f"{name} must resolve to an OCI index")
    found: set[str] = set()
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        platform = manifest.get("platform")
        annotations = manifest.get("annotations")
        if (
            isinstance(platform, dict)
            and platform.get("os") == "unknown"
            and platform.get("architecture") == "unknown"
            and isinstance(annotations, dict)
            and annotations.get("vnd.docker.reference.type") == "attestation-manifest"
            and DIGEST.fullmatch(str(manifest.get("digest", ""))) is not None
        ):
            found.add(str(manifest["digest"]))
    require(found, f"{name} lacks build attestation descriptors")
    return found


def validate_add_on_platforms(
    *,
    index: dict[str, Any],
    platform_images: dict[str, dict[str, Any]],
    expected_version: str,
    expected_commit: str,
    compatibility: dict[str, Any],
) -> dict[str, str]:
    descriptors = runtime_descriptors(index, "add-on image")
    core = compatibility["core"]
    optimizer = compatibility["optimizer"]
    expected_common = {
        "io.hass.version": expected_version,
        "org.opencontainers.image.version": expected_version,
        "org.opencontainers.image.revision": expected_commit,
        "com.sourceful.ftw.core.version": str(core["version"]),
        "com.sourceful.ftw.core.digest": str(core["digest"]),
        "com.sourceful.ftw.optimizer.version": str(optimizer["version"]),
        "com.sourceful.ftw.optimizer.digest": str(optimizer["digest"]),
        "com.sourceful.ftw.update-owner": "home_assistant_supervisor",
    }
    result: dict[str, str] = {}
    for add_on_arch, oci_arch in ADD_ON_ARCHITECTURES.items():
        image = platform_images.get(oci_arch)
        require(isinstance(image, dict), f"add-on linux/{oci_arch} config is missing")
        labels = image_labels(image)
        expected_labels = {**expected_common, "io.hass.arch": add_on_arch}
        for key, value in expected_labels.items():
            require(labels.get(key) == value, f"add-on linux/{oci_arch} label {key} mismatch")
        result[add_on_arch] = str(descriptors[oci_arch]["digest"])
    return result


def validate_source_index_link(
    *,
    source_index: dict[str, Any],
    name: str,
    architecture: str,
    expected_runtime_digest: str,
    final_attestations: set[str],
) -> None:
    source_descriptors = runtime_descriptors(
        source_index,
        name,
        required_architectures=(architecture,),
    )
    require(
        str(source_descriptors[architecture]["digest"]) == expected_runtime_digest,
        f"{name} does not match final index",
    )
    source_attestations = attestation_descriptor_digests(source_index, name)
    require(
        source_attestations.issubset(final_attestations),
        f"{name} build attestations are missing from final index",
    )


def inspect_add_on_image(
    *,
    image: str,
    digest: str,
    version: str,
    source_commit: str,
    compatibility: dict[str, Any],
) -> dict[str, str]:
    require(DIGEST.fullmatch(digest) is not None, "add-on resume digest is invalid")
    reference = f"{image}@{digest}"
    actual = command_output(
        ["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"]
    )
    require(actual == digest, "add-on registry digest mismatch")
    index = json.loads(command_output(["docker", "buildx", "imagetools", "inspect", reference, "--raw"]))
    require(isinstance(index, dict), "add-on registry index is invalid")
    descriptors = runtime_descriptors(index, "add-on image")
    final_attestations = attestation_descriptor_digests(index, "add-on image")

    platform_images: dict[str, dict[str, Any]] = {}
    for architecture, descriptor in descriptors.items():
        child = command_output(
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
        parsed = json.loads(child)
        require(isinstance(parsed, dict), f"add-on linux/{architecture} config is invalid")
        platform_images[architecture] = parsed

    platform_digests = validate_add_on_platforms(
        index=index,
        platform_images=platform_images,
        expected_version=version,
        expected_commit=source_commit,
        compatibility=compatibility,
    )
    registry_prefix, image_name = image.rsplit("/", 1)
    outputs: dict[str, str] = {"image": image, **{f"{key}_platform_digest": value for key, value in platform_digests.items()}}
    for add_on_arch, oci_arch in ADD_ON_ARCHITECTURES.items():
        source_image = f"{registry_prefix}/{add_on_arch}-{image_name}"
        source_digest = optional_image_digest(f"{source_image}:{version}")
        require(source_digest is not None, f"{add_on_arch} source image version tag is missing")
        source_index = json.loads(
            command_output(
                ["docker", "buildx", "imagetools", "inspect", f"{source_image}@{source_digest}", "--raw"]
            )
        )
        require(isinstance(source_index, dict), f"{add_on_arch} source image index is invalid")
        validate_source_index_link(
            source_index=source_index,
            name=f"{add_on_arch} source image",
            architecture=oci_arch,
            expected_runtime_digest=platform_digests[add_on_arch],
            final_attestations=final_attestations,
        )
        outputs[f"{add_on_arch}_source_image"] = source_image
        outputs[f"{add_on_arch}_source_digest"] = source_digest
    return outputs


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


def attestation_verify_command(
    *,
    image: str,
    digest: str,
    repository: str,
    source_commit: str,
    cert_identity: str = RELEASE_WORKFLOW_IDENTITY,
    from_oci: bool = False,
) -> list[str]:
    require(DIGEST.fullmatch(digest) is not None, "attestation digest is invalid")
    require(COMMIT.fullmatch(source_commit) is not None, "attestation source commit is invalid")
    require(
        cert_identity in (RELEASE_WORKFLOW_IDENTITY, FINALIZE_WORKFLOW_IDENTITY),
        "attestation workflow identity is invalid",
    )
    command = [
        "gh",
        "attestation",
        "verify",
        f"oci://{image}@{digest}",
        "--repo",
        repository,
        "--predicate-type",
        SBOM_PREDICATE_TYPE,
        "--source-digest",
        source_commit,
        "--source-ref",
        "refs/heads/main",
        "--cert-identity",
        cert_identity,
        "--format",
        "json",
    ]
    if from_oci:
        command.append("--bundle-from-oci")
    return command


def verified_sbom_predicate(
    verification: Any,
    *,
    expected_name: str,
    expected_digest: str,
) -> dict[str, Any]:
    require(isinstance(verification, list) and verification, "no verified SBOM attestations found")
    predicates: list[dict[str, Any]] = []
    for item in verification:
        require(isinstance(item, dict), "verified attestation entry is invalid")
        result = item.get("verificationResult")
        require(isinstance(result, dict), "verified attestation result is missing")
        statement = result.get("statement")
        require(isinstance(statement, dict), "verified attestation statement is missing")
        require(statement.get("predicateType") == SBOM_PREDICATE_TYPE, "SBOM predicate type mismatch")
        subjects = statement.get("subject")
        require(isinstance(subjects, list) and len(subjects) == 1, "SBOM attestation subject is invalid")
        subject = subjects[0]
        require(isinstance(subject, dict), "SBOM attestation subject is invalid")
        require(subject.get("name") == expected_name, "SBOM attestation subject name mismatch")
        digest = subject.get("digest")
        require(isinstance(digest, dict), "SBOM attestation subject digest is missing")
        require(digest.get("sha256") == expected_digest.removeprefix("sha256:"), "SBOM attestation digest mismatch")
        predicate = statement.get("predicate")
        require(isinstance(predicate, dict), "SBOM attestation predicate is missing")
        predicates.append(predicate)
    canonical = {canonical_json(predicate) for predicate in predicates}
    require(len(canonical) == 1, "verified SBOM attestations disagree")
    return predicates[0]


def verify_sbom_from_api(
    *,
    image: str,
    digest: str,
    repository: str,
    source_commit: str,
) -> dict[str, Any]:
    output = command_output(
        attestation_verify_command(
            image=image,
            digest=digest,
            repository=repository,
            source_commit=source_commit,
        )
    )
    return verified_sbom_predicate(
        json.loads(output),
        expected_name=image,
        expected_digest=digest,
    )


def verify_sbom_from_oci(
    *,
    image: str,
    digest: str,
    repository: str,
    attestation_source_commit: str,
    cert_identity: str,
    expected_predicate: dict[str, Any],
    allow_missing: bool,
) -> bool:
    result = run(
        attestation_verify_command(
            image=image,
            digest=digest,
            repository=repository,
            source_commit=attestation_source_commit,
            cert_identity=cert_identity,
            from_oci=True,
        )
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if allow_missing and "no attestations found in the OCI registry" in detail:
            return False
        raise GateError(f"could not verify OCI SBOM attestation: {detail}")
    predicate = verified_sbom_predicate(
        json.loads(result.stdout),
        expected_name=image,
        expected_digest=digest,
    )
    require(predicate == expected_predicate, "OCI SBOM differs from verified GitHub attestation")
    return True


def validate_sbom_artifact(path: pathlib.Path, expected_predicate: dict[str, Any], architecture: str) -> None:
    artifact = load_json(path)
    require(artifact == expected_predicate, f"{architecture} SBOM artifact differs from signed attestation")


def write_beta_release_manifest(
    *,
    path: pathlib.Path,
    version: str,
    digest: str,
    source_commit: str,
) -> None:
    compatibility = load_yaml(ROOT / "compatibility.yaml")
    require(compatibility.get("add_on", {}).get("version") == version, "release manifest version mismatch")
    require(DIGEST.fullmatch(digest) is not None, "release manifest digest is invalid")
    require(COMMIT.fullmatch(source_commit) is not None, "release manifest source commit is invalid")
    core = compatibility["core"]
    optimizer = compatibility["optimizer"]
    drivers = compatibility["drivers"]
    baseline = drivers["tested_baseline"]
    manifest = {
        "schema_version": 1,
        "channel": "beta",
        "version": version,
        "image": compatibility["add_on"]["image"],
        "manifest_digest": digest,
        "source_commit": source_commit,
        "update_owner": "home_assistant_supervisor",
        "core": {
            "version": core["version"],
            "digest": core["digest"],
            "commit": core["commit"],
        },
        "optimizer": {
            "version": optimizer["version"],
            "digest": optimizer["digest"],
            "commit": optimizer["commit"],
            "name": "ftw-optimizer",
            "protocol_version": 1,
            "plan_schema_version": 1,
            "required_features": ["champion"],
            "conditional_features": ["recourse", "multistage"],
        },
        "drivers": {
            "source": drivers["source"],
            "channel": drivers["channel"],
            "manifest": drivers["manifest"],
            "tested_commit": baseline["commit"],
            "manifest_sha256": baseline["manifest_sha256"],
            "key_id": baseline["key_id"],
            "update_policy": "independent",
        },
        "sboms": ["ftw-amd64.spdx.json", "ftw-aarch64.spdx.json", "ftw.spdx.json"],
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def beta_resume_prepare(args: argparse.Namespace) -> None:
    config = load_yaml(ROOT / "ftw/config.yaml")
    require(config.get("version") == args.version, "resume version differs from config.yaml")
    compatibility = validate_resume_source(args.source_commit, args.version)
    require(
        compatibility.get("add_on", {}).get("manifest_digest") == "__PUBLISHED_BY_BETA_WORKFLOW__",
        "resume publisher marker is missing",
    )
    run_record, jobs, requested_version = source_run_evidence(args.repository, args.source_run_id)
    validate_resume_run(
        run_record=run_record,
        jobs=jobs,
        requested_version=requested_version,
        expected_version=args.version,
        expected_source_commit=args.source_commit,
    )
    image = str(compatibility["add_on"]["image"])
    release_target_state(args.repository, image, args.version, args.digest)
    verify_current_driver_baseline(compatibility["drivers"])
    for key, name in (("core", "Core"), ("optimizer", "Optimizer")):
        item = compatibility[key]
        inspect_pinned_image(name, item["image"], item["digest"], item["version"], item["commit"])
    outputs = inspect_add_on_image(
        image=image,
        digest=args.digest,
        version=args.version,
        source_commit=args.source_commit,
        compatibility=compatibility,
    )
    for name, value in outputs.items():
        write_output(name, value)


def beta_resume_evidence(args: argparse.Namespace) -> None:
    require(COMMIT.fullmatch(args.source_commit) is not None, "resume source commit is invalid")
    require(COMMIT.fullmatch(args.finalizer_commit) is not None, "finalizer commit is invalid")
    architecture_evidence = (
        ("amd64", args.amd64_image, args.amd64_digest, args.amd64_sbom),
        ("aarch64", args.aarch64_image, args.aarch64_digest, args.aarch64_sbom),
    )
    for architecture, image, digest, sbom_path in architecture_evidence:
        predicate = verify_sbom_from_api(
            image=image,
            digest=digest,
            repository=args.repository,
            source_commit=args.source_commit,
        )
        validate_sbom_artifact(sbom_path, predicate, architecture)

    index_predicate = verify_sbom_from_api(
        image=args.image,
        digest=args.digest,
        repository=args.repository,
        source_commit=args.source_commit,
    )
    args.index_sbom.write_text(
        json.dumps(index_predicate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    exists = verify_sbom_from_oci(
        image=args.image,
        digest=args.digest,
        repository=args.repository,
        attestation_source_commit=args.finalizer_commit,
        cert_identity=FINALIZE_WORKFLOW_IDENTITY,
        expected_predicate=index_predicate,
        allow_missing=True,
    )
    write_output("index_oci_attestation_exists", str(exists).lower())


def beta_resume_recheck(args: argparse.Namespace) -> None:
    compatibility = load_yaml(ROOT / "compatibility.yaml")
    release_target_state(
        args.repository,
        str(compatibility["add_on"]["image"]),
        args.version,
        args.digest,
    )


def beta_resume_verify_oci(args: argparse.Namespace) -> None:
    require(COMMIT.fullmatch(args.source_commit) is not None, "resume source commit is invalid")
    require(COMMIT.fullmatch(args.finalizer_commit) is not None, "finalizer commit is invalid")
    predicate = load_json(args.index_sbom)
    verify_sbom_from_oci(
        image=args.image,
        digest=args.digest,
        repository=args.repository,
        attestation_source_commit=args.finalizer_commit,
        cert_identity=FINALIZE_WORKFLOW_IDENTITY,
        expected_predicate=predicate,
        allow_missing=False,
    )


def beta_manifest(args: argparse.Namespace) -> None:
    write_beta_release_manifest(
        path=args.output,
        version=args.version,
        digest=args.digest,
        source_commit=args.source_commit,
    )


def beta_resume_final_state(args: argparse.Namespace) -> None:
    tag = f"ftw-v{args.version}"
    tag_target = command_output(["git", "ls-remote", "origin", f"refs/tags/{tag}"])
    fields = tag_target.split()
    require(len(fields) == 2 and fields[0] == args.source_commit, "final beta Git tag target mismatch")
    release = json.loads(
        command_output(
            [
                "gh",
                "release",
                "view",
                tag,
                "--repo",
                args.repository,
                "--json",
                "tagName,isDraft,isPrerelease,targetCommitish,assets",
            ]
        )
    )
    require(isinstance(release, dict), "final beta release record is invalid")
    require(release.get("tagName") == tag, "final beta release tag mismatch")
    require(release.get("isDraft") is False, "final beta release must not be draft")
    require(release.get("isPrerelease") is True, "final beta release must be a prerelease")
    require(release.get("targetCommitish") == args.source_commit, "final beta release target mismatch")
    assets = release.get("assets")
    require(isinstance(assets, list), "final beta release assets are missing")
    names = {asset.get("name") for asset in assets if isinstance(asset, dict)}
    expected = {"release-manifest.json", "ftw-amd64.spdx.json", "ftw-aarch64.spdx.json", "ftw.spdx.json"}
    require(names == expected, "final beta release assets mismatch")
    for name in expected:
        require((args.evidence_dir / name).is_file(), f"local final beta evidence is missing: {name}")
    with tempfile.TemporaryDirectory() as directory:
        command_output(
            [
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                args.repository,
                "--dir",
                directory,
            ]
        )
        downloaded = pathlib.Path(directory)
        for name in expected:
            validate_same_json(load_json(args.evidence_dir / name), load_json(downloaded / name))
    compatibility = load_yaml(ROOT / "compatibility.yaml")
    image = str(compatibility["add_on"]["image"])
    require(optional_image_digest(f"{image}:{args.version}") == args.digest, "final version digest changed")
    require(optional_image_digest(f"{image}:beta") == args.digest, "final beta alias digest changed")


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

    resume = commands.add_parser("beta-resume-prepare")
    resume.add_argument("--version", required=True)
    resume.add_argument("--digest", required=True)
    resume.add_argument("--source-commit", required=True)
    resume.add_argument("--source-run-id", required=True)
    resume.add_argument("--repository", required=True)
    resume.set_defaults(handler=beta_resume_prepare)

    evidence = commands.add_parser("beta-resume-evidence")
    evidence.add_argument("--repository", required=True)
    evidence.add_argument("--source-commit", required=True)
    evidence.add_argument("--finalizer-commit", required=True)
    evidence.add_argument("--image", required=True)
    evidence.add_argument("--digest", required=True)
    evidence.add_argument("--amd64-image", required=True)
    evidence.add_argument("--amd64-digest", required=True)
    evidence.add_argument("--amd64-sbom", type=pathlib.Path, required=True)
    evidence.add_argument("--aarch64-image", required=True)
    evidence.add_argument("--aarch64-digest", required=True)
    evidence.add_argument("--aarch64-sbom", type=pathlib.Path, required=True)
    evidence.add_argument("--index-sbom", type=pathlib.Path, required=True)
    evidence.set_defaults(handler=beta_resume_evidence)

    recheck = commands.add_parser("beta-resume-recheck")
    recheck.add_argument("--version", required=True)
    recheck.add_argument("--digest", required=True)
    recheck.add_argument("--repository", required=True)
    recheck.set_defaults(handler=beta_resume_recheck)

    verify_oci = commands.add_parser("beta-resume-verify-oci")
    verify_oci.add_argument("--repository", required=True)
    verify_oci.add_argument("--source-commit", required=True)
    verify_oci.add_argument("--finalizer-commit", required=True)
    verify_oci.add_argument("--image", required=True)
    verify_oci.add_argument("--digest", required=True)
    verify_oci.add_argument("--index-sbom", type=pathlib.Path, required=True)
    verify_oci.set_defaults(handler=beta_resume_verify_oci)

    manifest = commands.add_parser("beta-manifest")
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--digest", required=True)
    manifest.add_argument("--source-commit", required=True)
    manifest.add_argument("--output", type=pathlib.Path, required=True)
    manifest.set_defaults(handler=beta_manifest)

    final_state = commands.add_parser("beta-resume-final-state")
    final_state.add_argument("--version", required=True)
    final_state.add_argument("--digest", required=True)
    final_state.add_argument("--source-commit", required=True)
    final_state.add_argument("--repository", required=True)
    final_state.add_argument("--evidence-dir", type=pathlib.Path, required=True)
    final_state.set_defaults(handler=beta_resume_final_state)

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
