#!/usr/bin/env python3
"""Validate the repository, app manifest, and immutable release record."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Any

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"^__[A-Z0-9_]+__$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
BETA_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-beta\.[0-9]+$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PILOT_CHECKS = {
    "install",
    "boot_readiness",
    "persistence",
    "optimizer_fallback",
    "optimizer_recovery",
    "update",
    "rollback",
    "artifact_match",
    "active_solver",
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


def is_placeholder(value: object) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER.fullmatch(value))


def validate_common(config: dict[str, Any], compat: dict[str, Any]) -> None:
    repository = load_yaml(ROOT / "repository.yaml")
    require(repository.get("name"), "repository.yaml needs name")
    require(repository.get("url") == "https://github.com/srcfl/home-assistant-addons", "repository URL is wrong")

    require(not (ROOT / "ftw" / "build.yaml").exists(), "build.yaml is obsolete and must not exist")
    require(config.get("slug") == "ftw", "app slug must be ftw")
    require(config.get("arch") == ["amd64", "aarch64"], "app must list amd64 and aarch64 in that order")
    require(config.get("image") == "ghcr.io/srcfl/home-assistant-addons/ftw", "app image name is wrong")
    require(config.get("host_network") is True, "FTW needs host networking for local device access")
    require(config.get("backup") == "cold", "FTW backups must be cold")
    require(config.get("stage", "stable") in ("experimental", "stable"), "app stage is invalid")

    environment = config.get("environment")
    require(isinstance(environment, dict), "app environment must be an object")
    require(str(environment.get("FTW_SELFUPDATE_ENABLED")) == "0", "self-update must be explicitly off")
    require(environment.get("FTW_OPTIMIZER_TRANSPORT") == "unix", "optimizer transport must be unix")
    require(
        environment.get("FTW_OPTIMIZER_SOCKET") == "/run/ftw-optimizer/optimizer.sock",
        "optimizer socket is wrong",
    )

    require(compat.get("schema_version") == 1, "compatibility schema_version must be 1")
    app = compat.get("add_on")
    require(isinstance(app, dict), "compatibility add_on must be an object")
    require(app.get("version") == config.get("version"), "config and compatibility versions differ")
    require(app.get("architectures") == config.get("arch"), "config and compatibility architectures differ")
    require(app.get("image") == config.get("image"), "config and compatibility image names differ")
    require(compat.get("update_owner") == "home_assistant_supervisor", "Supervisor must own update")
    require("updater" not in compat, "compatibility must not define an FTW updater")

    core = compat.get("core")
    require(isinstance(core, dict), "compatibility core must be an object")
    require(core.get("mode") == "home_assistant_add_on", "Core must use add-on mode")
    require(core.get("self_update") is False, "Core self-update must be false")

    optimizer = compat.get("optimizer")
    require(isinstance(optimizer, dict), "compatibility optimizer must be an object")
    require(optimizer.get("name") == "ftw-optimizer", "optimizer handshake name is wrong")
    require(optimizer.get("protocol_version") == 1, "optimizer protocol must be 1")
    require(optimizer.get("plan_schema_version") == 1, "optimizer plan schema must be 1")
    require(optimizer.get("transport") == "unix", "optimizer compatibility transport must be unix")
    require(optimizer.get("socket") == "/run/ftw-optimizer/optimizer.sock", "optimizer compatibility socket is wrong")
    require("champion" in optimizer.get("required_features", []), "optimizer must require champion")
    require(
        {"recourse", "multistage"}.issubset(set(optimizer.get("conditional_features", []))),
        "optimizer must record conditional recourse and multistage features",
    )

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


def require_release_values(compat: dict[str, Any], *, require_app_digest: bool) -> None:
    app = compat["add_on"]
    core = compat["core"]
    optimizer = compat["optimizer"]
    values = {
        "Core version": core.get("version"),
        "Core digest": core.get("digest"),
        "Core commit": core.get("commit"),
        "Optimizer version": optimizer.get("version"),
        "Optimizer digest": optimizer.get("digest"),
        "Optimizer commit": optimizer.get("commit"),
    }
    for name, value in values.items():
        require(not is_placeholder(value) and value not in (None, ""), f"{name} is still a placeholder")
    if require_app_digest:
        require(not is_placeholder(app.get("manifest_digest")), "add-on manifest digest is still a placeholder")
        require(DIGEST.fullmatch(str(app["manifest_digest"])) is not None, "add-on manifest digest is invalid")
    else:
        require(
            app.get("manifest_digest") == "__PUBLISHED_BY_BETA_WORKFLOW__"
            or DIGEST.fullmatch(str(app.get("manifest_digest"))) is not None,
            "beta add-on digest must be the publisher marker or a published digest",
        )
    require(DIGEST.fullmatch(str(core["digest"])) is not None, "Core digest is invalid")
    require(COMMIT.fullmatch(str(core["commit"])) is not None, "Core commit is invalid")
    require(DIGEST.fullmatch(str(optimizer["digest"])) is not None, "Optimizer digest is invalid")
    require(COMMIT.fullmatch(str(optimizer["commit"])) is not None, "Optimizer commit is invalid")

    baseline = compat["drivers"].get("tested_baseline")
    require(isinstance(baseline, dict), "tested driver baseline is missing")
    require(COMMIT.fullmatch(str(baseline.get("commit", ""))) is not None, "tested driver commit is invalid")
    require(
        SHA256.fullmatch(str(baseline.get("manifest_sha256", ""))) is not None,
        "tested driver manifest SHA-256 is invalid",
    )
    require(baseline.get("evidence"), "tested driver baseline evidence is missing")


def validate_beta_pilot(version: str, compat: dict[str, Any]) -> None:
    qualification = compat["qualification"]
    ha_gate = qualification.get("home_assistant_os_supervisor", {})
    record_name = f"pilot/{version}.yaml"
    require(ha_gate.get("record") == record_name, "Home Assistant pilot record path is wrong")
    record = load_yaml(ROOT / record_name)
    require(record.get("schema_version") == 1, "pilot schema_version must be 1")
    require(record.get("add_on_version") == version, "pilot add-on version differs")
    require(record.get("status") in ("blocked", "passed"), "pilot status is invalid")

    candidate = record.get("candidate")
    require(isinstance(candidate, dict), "pilot candidate must be an object")
    for name in ("core", "optimizer"):
        expected = compat[name]
        actual = candidate.get(name)
        require(isinstance(actual, dict), f"pilot {name} candidate is missing")
        for field in ("version", "commit", "digest"):
            require(actual.get(field) == expected.get(field), f"pilot {name} {field} differs")
    baseline = compat["drivers"]["tested_baseline"]
    pilot_drivers = candidate.get("drivers")
    require(isinstance(pilot_drivers, dict), "pilot driver candidate is missing")
    require(pilot_drivers.get("channel") == compat["drivers"]["channel"], "pilot driver channel differs")
    require(pilot_drivers.get("tested_commit") == baseline["commit"], "pilot driver commit differs")
    require(
        pilot_drivers.get("manifest_sha256") == baseline["manifest_sha256"],
        "pilot driver manifest SHA-256 differs",
    )

    checks = record.get("checks")
    require(isinstance(checks, dict), "pilot checks must be an object")
    require(PILOT_CHECKS.issubset(checks), "pilot record lacks required checks")
    for name in PILOT_CHECKS:
        check = checks[name]
        require(isinstance(check, dict), f"pilot check {name} must be an object")
        require(check.get("expected"), f"pilot check {name} lacks an expected result")
        require(check.get("status") in ("blocked", "passed"), f"pilot check {name} status is invalid")
        if check["status"] == "passed":
            require(check.get("evidence"), f"passed pilot check {name} lacks evidence")
    gate_status = ha_gate.get("status")
    require(gate_status in ("blocked", "passed"), "Home Assistant gate status is invalid")
    if gate_status == "blocked":
        require(record.get("status") == "blocked", "blocked Home Assistant gate needs a blocked pilot record")
    else:
        require(record.get("status") == "passed", "passed Home Assistant gate needs a passed pilot record")
        require(ha_gate.get("evidence"), "passed Home Assistant gate lacks evidence")
        require(COMMIT.fullmatch(str(candidate.get("source_commit", ""))) is not None, "pilot source commit is invalid")
        require(DIGEST.fullmatch(str(candidate.get("manifest_digest", ""))) is not None, "pilot digest is invalid")
        require(all(checks[name]["status"] == "passed" for name in PILOT_CHECKS), "passed pilot has blocked checks")


def validate_channel(channel: str, config: dict[str, Any], compat: dict[str, Any]) -> None:
    version = str(config.get("version", ""))
    if channel == "bootstrap":
        require(version == "0.0.0-dev", "bootstrap config version must be 0.0.0-dev")
        require(compat["add_on"].get("channel") == "bootstrap", "bootstrap compatibility channel is wrong")
        require(config.get("stage") == "experimental", "bootstrap app stage must be experimental")
        return

    require_release_values(compat, require_app_digest=channel == "stable")
    qualification = compat.get("qualification")
    require(isinstance(qualification, dict), "qualification must be an object")
    require(qualification.get("upstream_gate", {}).get("status") == "passed", "upstream gate has not passed")
    require(qualification.get("upstream_gate", {}).get("evidence"), "upstream gate evidence is missing")

    if channel == "beta":
        require(BETA_SEMVER.fullmatch(version) is not None, "beta version must match X.Y.Z-beta.N")
        require(compat["add_on"].get("channel") == "beta", "compatibility channel must be beta")
        require(config.get("stage") == "experimental", "beta app stage must be experimental")
        validate_beta_pilot(version, compat)
        return

    require(SEMVER.fullmatch(version) is not None, "stable version must match X.Y.Z")
    require(compat["add_on"].get("channel") == "stable", "compatibility channel must be stable")
    require("stage" not in config, "stable must use Home Assistant's default stable stage")
    ha_gate = qualification.get("home_assistant_os_supervisor", {})
    require(ha_gate.get("status") == "passed", "Home Assistant OS and Supervisor pilot has not passed")
    require(ha_gate.get("evidence"), "Home Assistant pilot evidence is missing")
    promoted = qualification.get("promoted_from_beta", {})
    require(promoted.get("channel") == "beta", "promoted release channel must be beta")
    require(BETA_SEMVER.fullmatch(str(promoted.get("version", ""))) is not None, "promoted beta version is missing")
    require(str(promoted["version"]).split("-beta.", 1)[0] == version, "stable and beta SemVer bases differ")
    require(promoted.get("manifest_digest") == compat["add_on"]["manifest_digest"], "stable digest differs from beta")
    require(COMMIT.fullmatch(str(promoted.get("source_commit", ""))) is not None, "promoted beta commit is missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=("auto", "bootstrap", "beta", "stable"), default="auto")
    args = parser.parse_args()
    try:
        config = load_yaml(ROOT / "ftw" / "config.yaml")
        compat = load_yaml(ROOT / "compatibility.yaml")
        channel = args.channel
        if channel == "auto":
            channel = str(compat.get("add_on", {}).get("channel", ""))
            require(channel in ("bootstrap", "beta", "stable"), "compatibility channel is invalid")
        validate_common(config, compat)
        validate_channel(channel, config, compat)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"repository validation passed for {channel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
