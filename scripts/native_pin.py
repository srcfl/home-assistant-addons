#!/usr/bin/env python3
"""Check or move the ftw-0x-beta pin against FTW's ftw-native-release.json.

  native_pin.py check            verify config.yaml/Dockerfile agree and match
                                 the release's own receipt and .sha256 files
  native_pin.py bump [TAG]       rewrite the pin to TAG (default: newest new-line
                                 0.x beta) after the same verification

It only edits files in this repository. The pin workflow merges its pull request after Check passes; Supervisor then builds the app on the device.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "ftw-0x-beta"
REPO = "srcfl/ftw"
TAG_RE = re.compile(r"^v0\.(\d+)\.(\d+)-beta\.(\d+)$")
MIN_MINOR = 131  # the new 0.x line starts at v0.131.0-beta.1
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ftw-ha-native-pin"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def asset(tag: str, name: str) -> bytes:
    return fetch(f"https://github.com/{REPO}/releases/download/{tag}/{name}")


def valid_tag(tag: str) -> bool:
    m = TAG_RE.match(tag)
    return bool(m) and int(m.group(1)) >= MIN_MINOR


def tag_order(tag: str) -> tuple[int, ...]:
    if not valid_tag(tag):
        raise SystemExit(f"{tag} is not a new-line 0.x beta tag")
    return tuple(int(x) for x in TAG_RE.fullmatch(tag).groups())


def latest_tag() -> str:
    releases = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases?per_page=50"))
    tags = [r["tag_name"] for r in releases if not r.get("draft") and valid_tag(r["tag_name"])]
    if not tags:
        raise SystemExit("no new-line 0.x beta found")
    return max(tags, key=tag_order)


def receipt(tag: str) -> dict[str, str]:
    if not valid_tag(tag):
        raise SystemExit(f"{tag} is not a new-line 0.x beta tag")
    data = json.loads(asset(tag, "ftw-native-release.json"))
    if data.get("schema") != 1 or data.get("channel") != "beta" or data.get("tag") != tag:
        raise SystemExit(f"{tag}: ftw-native-release.json does not describe this beta")
    sums = data.get("sha256") or {}
    for arch in ("amd64", "arm64"):
        want = sums.get(arch, "")
        if not HEX64.match(want):
            raise SystemExit(f"{tag}: receipt lacks a sha256 for {arch}")
        line = asset(tag, f"ftw-linux-{arch}.tar.gz.sha256").decode().split()
        if line != [want, f"ftw-linux-{arch}.tar.gz"]:
            raise SystemExit(f"{tag}: {arch} .sha256 file disagrees with the receipt")
    return {"amd64": sums["amd64"], "arm64": sums["arm64"]}


def read_pin() -> tuple[str, str, dict[str, str]]:
    config = (APP / "config.yaml").read_text()
    build = (APP / "Dockerfile").read_text()
    if (APP / "build.yaml").exists():
        raise SystemExit("keep the native pins in Dockerfile, not deprecated build.yaml")

    def field(text: str, key: str) -> str:
        m = re.search(rf'^ARG {key}=([^\n]+)$', text, re.M)
        if m is None:
            m = re.search(rf'^\s*{key}:\s*"?([^"\n]+)"?\s*$', text, re.M)
        if not m:
            raise SystemExit(f"missing {key}")
        return m.group(1).strip()

    tag = field(build, "FTW_VERSION")
    tag_order(tag)
    version = field(config, "version")
    revision = tag[1:].replace("-beta.", "-beta")
    if ((version != tag[1:] and not re.fullmatch(re.escape(revision) + r"-[1-9][0-9]*", version))
            or field(config, "FTW_BUNDLE_VERSION") != version or field(config, "FTW_IMAGE_TAG") != tag):
        raise SystemExit("config.yaml and Dockerfile pin different versions")
    if field(config, "slug") != "ftw-0x-beta" or re.search(r"^image:", config, re.M):
        raise SystemExit("ftw-0x-beta must keep its slug and have no image: key (built on the device)")
    return tag, version, {"amd64": field(build, "FTW_SHA256_AMD64"), "arm64": field(build, "FTW_SHA256_ARM64")}


def write_pin(tag: str, sums: dict[str, str]) -> None:
    old_tag, old_version, old_sums = read_pin()
    version = old_version if tag == old_tag else tag[1:]
    config = (APP / "config.yaml").read_text()
    config = config.replace(f'"{old_version}"', f'"{version}"').replace(old_tag, tag)
    build = (APP / "Dockerfile").read_text().replace(old_tag, tag)
    for arch in ("amd64", "arm64"):
        build = build.replace(old_sums[arch], sums[arch])
    (APP / "config.yaml").write_text(config)
    (APP / "Dockerfile").write_text(build)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        tag, _, sums = read_pin()
        if receipt(tag) != sums:
            raise SystemExit(f"pinned sha256 values differ from {tag}'s receipt")
        print(f"ok: ftw-0x-beta pins {tag}")
    elif cmd == "bump":
        tag = argv[2] if len(argv) > 2 else latest_tag()
        current, _, _ = read_pin()
        if tag_order(tag) < tag_order(current):
            print(f"ignored older beta {tag}; already pinned to {current}")
            return 0
        sums = receipt(tag)
        write_pin(tag, sums)
        if tag != current:
            changelog = APP / "CHANGELOG.md"
            entry = (f"## {tag[1:]}\n\n"
                     f"- Update FTW to [{tag}](https://github.com/{REPO}/releases/tag/{tag}).\n\n")
            changelog.write_text(changelog.read_text().replace("# Changelog\n\n", "# Changelog\n\n" + entry, 1))
        read_pin()
        print(f"pinned {tag}")
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
