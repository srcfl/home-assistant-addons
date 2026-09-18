#!/usr/bin/env python3
"""Validate the repository, both app manifests and the compatibility record."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Any

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/srcfl/home-assistant-addons/ftw"
CORE_IMAGE = "ghcr.io/srcfl/ftw"
REPOSITORY_URL = "https://github.com/srcfl/home-assistant-addons"
CORE_RELEASES = "https://github.com/srcfl/ftw/releases/tag/"
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
BETA_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-beta\.[0-9]+$")
CORE_SEMVER = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-beta\.[0-9]+)?$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHANNELS: dict[str, dict[str, Any]] = {
    "beta": {"slug": "ftw-beta", "name": "FTW (beta)", "stage": "experimental", "version": BETA_SEMVER},
    "stable": {"slug": "ftw", "name": "FTW", "stage": None, "version": SEMVER},
}


class ValidationError(Exception):
    pass


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = yaml.safe_load(source)
    if not isinstance(value, dict):
        raise ValidationError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def add_on_directory(channel: str) -> pathlib.Path:
    return ROOT / str(CHANNELS[channel]["slug"])


def add_on_version(core_version: str) -> str:
    require(CORE_SEMVER.fullmatch(str(core_version)) is not None, f"Core version is invalid: {core_version}")
    return str(core_version)[1:]


def validate_core_image_tag_contract(dockerfile: str) -> None:
    argument = re.search(r"(?m)^ARG CORE_VERSION[ \t]*$", dockerfile)
    image_tag = re.search(
        r"(?m)^[ \t]+FTW_IMAGE_TAG=\$\{CORE_VERSION\}(?:[ \t]+\\)?[ \t]*$",
        dockerfile,
    )
    require(argument is not None, "Dockerfile must declare the CORE_VERSION build argument")
    require(image_tag is not None, "Dockerfile must set FTW_IMAGE_TAG from CORE_VERSION")
    require(argument.start() < image_tag.start(), "Dockerfile must declare CORE_VERSION before FTW_IMAGE_TAG")


def validate_repository() -> None:
    repository = load_yaml(ROOT / "repository.yaml")
    require(bool(repository.get("name")), "repository.yaml needs name")
    require(repository.get("url") == REPOSITORY_URL, "repository URL is wrong")
    for channel in CHANNELS:
        require(not (add_on_directory(channel) / "build.yaml").exists(), "build.yaml is obsolete and must not exist")
    dockerfile = ROOT / "ftw" / "Dockerfile"
    require(dockerfile.is_file(), "ftw/Dockerfile is the shared build context and must exist")
    validate_core_image_tag_contract(dockerfile.read_text(encoding="utf-8"))
    require(not (ROOT / "ftw-beta" / "Dockerfile").exists(), "ftw-beta must not carry its own Dockerfile")


def validate_core_pin(core: Any, channel: str) -> None:
    require(isinstance(core, dict), f"{channel} Core pin must be an object")
    version = str(core.get("version", ""))
    require(CORE_SEMVER.fullmatch(version) is not None, f"{channel} Core version must match vX.Y.Z or vX.Y.Z-beta.N")
    if channel == "beta":
        require("-beta." in version, "beta Core version must be a prerelease")
    else:
        require("-beta." not in version, "stable Core version must not be a prerelease")
    require(DIGEST.fullmatch(str(core.get("digest", ""))) is not None, f"{channel} Core digest is invalid")
    require(COMMIT.fullmatch(str(core.get("commit", ""))) is not None, f"{channel} Core commit is invalid")
    require(core.get("release") == f"{CORE_RELEASES}{version}", f"{channel} Core release URL is wrong")


def validate_common(compat: dict[str, Any]) -> None:
    require(compat.get("schema_version") == 2, "compatibility schema_version must be 2")
    require(compat.get("image") == IMAGE, "compatibility image name is wrong")
    require(compat.get("update_owner") == "home_assistant_supervisor", "Supervisor must own update")
    require("updater" not in compat, "compatibility must not define an FTW updater")

    core = compat.get("core")
    require(isinstance(core, dict), "compatibility core must be an object")
    require(core.get("image") == CORE_IMAGE, "Core image name is wrong")
    require(core.get("mode") == "home_assistant_add_on", "Core must use add-on mode")
    require(core.get("self_update") is False, "Core self-update must be false")

    for channel, spec in CHANNELS.items():
        block = compat.get(channel)
        require(isinstance(block, dict), f"compatibility {channel} must be an object")
        require(block.get("add_on") == spec["slug"], f"compatibility {channel} add_on must be {spec['slug']}")

    drivers = compat.get("drivers")
    require(isinstance(drivers, dict), "compatibility drivers must be an object")
    require(drivers.get("source") == "https://github.com/srcfl/device-drivers", "driver source is wrong")
    require(drivers.get("channel") == "stable", "managed drivers must use the stable channel")
    require(
        drivers.get("manifest")
        == "https://github.com/srcfl/device-drivers/releases/download/drivers-stable/manifest.json",
        "stable driver manifest URL is wrong",
    )
    require(drivers.get("independently_updateable") is True, "managed drivers must update independently")
    require(drivers.get("bundled_role") == "offline_recovery", "bundled drivers are only offline recovery")
    require(drivers.get("user_directory") == "/data/drivers", "user driver directory is wrong")
    baseline = drivers.get("tested_baseline")
    require(isinstance(baseline, dict), "tested driver baseline is missing")
    require(COMMIT.fullmatch(str(baseline.get("commit", ""))) is not None, "tested driver commit is invalid")
    require(
        SHA256.fullmatch(str(baseline.get("manifest_sha256", ""))) is not None,
        "tested driver manifest SHA-256 is invalid",
    )
    require(baseline.get("key_id") == "ftw-drivers-2026-01", "tested driver key id is wrong")
    require(bool(baseline.get("evidence")), "tested driver baseline evidence is missing")

    qualification = compat.get("qualification")
    require(isinstance(qualification, dict), "qualification must be an object")
    pilot = qualification.get("home_assistant_os_supervisor")
    require(isinstance(pilot, dict), "Home Assistant pilot record must be an object")
    require(pilot.get("status") in ("blocked", "passed"), "Home Assistant pilot status is invalid")
    require(pilot.get("checklist") == "pilot/README.md", "Home Assistant pilot checklist path is wrong")
    if pilot["status"] == "passed":
        require(
            str(pilot.get("evidence", "")).startswith("https://"),
            "passed Home Assistant pilot needs public evidence",
        )
        require(
            BETA_SEMVER.fullmatch(str(pilot.get("add_on_version", ""))) is not None,
            "passed Home Assistant pilot must name the beta app version it ran on",
        )


def validate_beta(compat: dict[str, Any]) -> None:
    beta = compat["beta"]
    validate_core_pin(beta.get("core"), "beta")
    require(
        beta.get("version") == add_on_version(str(beta["core"]["version"])),
        "beta app version must mirror the Core version",
    )


def validate_stable(compat: dict[str, Any], *, required: bool) -> None:
    stable = compat["stable"]
    if stable.get("version") is None:
        require(not required, "stable channel has no promoted version")
        for field in ("promoted_from_beta", "manifest_digest", "source_commit", "core"):
            require(stable.get(field) is None, f"stable {field} must be null until the first promotion")
        return
    version = str(stable["version"])
    require(SEMVER.fullmatch(version) is not None, "stable app version must match X.Y.Z")
    promoted = str(stable.get("promoted_from_beta", ""))
    require(BETA_SEMVER.fullmatch(promoted) is not None, "stable must name the beta it was promoted from")
    require(promoted.split("-beta.", 1)[0] == version, "stable and promoted beta versions differ")
    require(DIGEST.fullmatch(str(stable.get("manifest_digest", ""))) is not None, "stable manifest digest is invalid")
    require(COMMIT.fullmatch(str(stable.get("source_commit", ""))) is not None, "stable source commit is invalid")
    validate_core_pin(stable.get("core"), "stable")
    require(add_on_version(str(stable["core"]["version"])) == version, "stable app version must mirror the Core version")
    require(
        compat["qualification"]["home_assistant_os_supervisor"].get("status") == "passed",
        "stable requires a passed Home Assistant OS and Supervisor pilot",
    )


def validate_add_on_config(config: dict[str, Any], compat: dict[str, Any], channel: str) -> None:
    spec = CHANNELS[channel]
    block = compat[channel]
    slug = str(spec["slug"])
    require(config.get("name") == spec["name"], f"{slug} name must be {spec['name']}")
    require(config.get("slug") == slug, f"app slug must be {slug}")
    require(config.get("url") == f"{REPOSITORY_URL}/tree/main/{slug}", f"{slug} url is wrong")
    require(config.get("arch") == ["amd64", "aarch64"], f"{slug} must list amd64 and aarch64 in that order")
    require(config.get("image") == IMAGE, f"{slug} image name is wrong")
    require(config.get("host_network") is True, "FTW needs host networking for local device access")
    require(config.get("backup") == "cold", "FTW backups must be cold")
    require("init" not in config, "init must stay at the Supervisor default so Docker's init reaps Core")
    if spec["stage"] is None:
        require("stage" not in config, f"{slug} must use Home Assistant's default stable stage")
    else:
        require(config.get("stage") == spec["stage"], f"{slug} stage must be {spec['stage']}")

    version = str(config.get("version", ""))
    require(spec["version"].fullmatch(version) is not None, f"{slug} version format is wrong")
    require(block.get("version") == version, f"{slug} config and compatibility versions differ")

    environment = config.get("environment")
    require(isinstance(environment, dict), f"{slug} environment must be an object")
    require(str(environment.get("FTW_SELFUPDATE_ENABLED")) == "0", "self-update must be explicitly off")
    require(environment.get("FTW_BUNDLE") == "home_assistant_addon", "FTW_BUNDLE must name the Home Assistant bundle")
    require(environment.get("FTW_BUNDLE_VERSION") == version, "FTW_BUNDLE_VERSION must match the app version")
    require(
        environment.get("FTW_IMAGE_TAG") == block["core"]["version"],
        "FTW_IMAGE_TAG must be the pinned Core release tag",
    )


def validate_channel(channel: str, compat: dict[str, Any]) -> None:
    if channel == "beta":
        validate_beta(compat)
    else:
        validate_stable(compat, required=True)
    config = load_yaml(add_on_directory(channel) / "config.yaml")
    validate_add_on_config(config, compat, channel)


def validate_all(compat: dict[str, Any]) -> list[str]:
    validate_channel("beta", compat)
    stable_config = add_on_directory("stable") / "config.yaml"
    if compat["stable"].get("version") is None:
        validate_stable(compat, required=False)
        require(not stable_config.exists(), "ftw/config.yaml must not exist before the first stable promotion")
        return ["beta"]
    validate_channel("stable", compat)
    return ["beta", "stable"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=("auto", "beta", "stable"), default="auto")
    args = parser.parse_args()
    try:
        validate_repository()
        compat = load_yaml(ROOT / "compatibility.yaml")
        validate_common(compat)
        if args.channel == "auto":
            channels = validate_all(compat)
        else:
            validate_channel(args.channel, compat)
            channels = [args.channel]
    except (OSError, yaml.YAMLError, ValidationError) as error:
        print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"repository validation passed for {', '.join(channels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
