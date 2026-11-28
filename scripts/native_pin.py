#!/usr/bin/env python3
"""Check or move the 0.x app pins against FTW's ftw-native-release.json.

  native_pin.py check            verify each app's manifest and Dockerfile agree
                                 and match the release's own receipt and
                                 .sha256 files
  native_pin.py bump [TAG]       rewrite a pin to TAG after the same checks.
                                 A beta tag (v0.X.Y-beta.N, default: the newest)
                                 moves ftw-0x-beta; a stable tag (v0.X.Y) moves
                                 the stable app in ftw-0x

The stable app stays out of the store until the first 0.x stable: its manifest
is kept as ftw-0x/unlisted.yaml, which Supervisor does not read, and its pins
are empty. The first stable bump writes ftw-0x/config.yaml, which lists it.

It only edits files in this repository. The pin workflow merges its pull request after Check passes; Supervisor then builds the app on the device.
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "ftw-0x-beta"
STABLE_APP = ROOT / "ftw-0x"
REPO = "srcfl/ftw"
TAG_RE = re.compile(r"^v0\.(\d+)\.(\d+)-beta\.(\d+)$")
STABLE_TAG_RE = re.compile(r"^v0\.(\d+)\.(\d+)$")
MIN_MINOR = 131  # the new 0.x line starts at v0.131.0-beta.1
SLUGS = {"beta": "ftw-0x-beta", "stable": "ftw"}
UNLISTED = "unlisted.yaml"  # the stable manifest before the first stable
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ATTEMPTS = 3
UNRELEASED = "# Changelog\n\n## Unreleased\n\n"
PAUSE_S = 2  # before the second attempt; twice that before the third


def fetch(url: str) -> bytes:
    """Read url. Try again after a timeout, a broken connection or an HTTP 5xx.

    One slow answer from GitHub used to fail the whole run, and a failed pin run
    leaves that release unpinned until the next one. An HTTP 4xx still fails at
    once: a missing file does not turn up by waiting.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "ftw-ha-native-pin"})
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        # OSError covers timeouts, refused or reset connections and HTTPError.
        # HTTPException covers an answer that was cut short.
        except (OSError, http.client.HTTPException) as err:
            client_error = isinstance(err, urllib.error.HTTPError) and err.code < 500
            if client_error or attempt == ATTEMPTS:
                raise
            pause = PAUSE_S * attempt
            print(f"{url}: {err!r}; attempt {attempt + 1} of {ATTEMPTS} in {pause} s", file=sys.stderr)
            time.sleep(pause)
    raise AssertionError("ATTEMPTS must be at least 1")


def asset(tag: str, name: str) -> bytes:
    return fetch(f"https://github.com/{REPO}/releases/download/{tag}/{name}")


def valid_tag(tag: str) -> bool:
    """A new-line 0.x beta tag."""
    m = TAG_RE.match(tag)
    return bool(m) and int(m.group(1)) >= MIN_MINOR


def channel(tag: str) -> str:
    """beta or stable, for a tag of the new 0.x line."""
    for name, pattern in (("beta", TAG_RE), ("stable", STABLE_TAG_RE)):
        m = pattern.match(tag)
        if m and int(m.group(1)) >= MIN_MINOR:
            return name
    raise SystemExit(f"{tag} is not a new-line 0.x beta or stable tag")


def tag_order(tag: str) -> tuple[int, ...]:
    """Sort key within one channel: (minor, patch, beta) or (minor, patch)."""
    pattern = TAG_RE if channel(tag) == "beta" else STABLE_TAG_RE
    return tuple(int(x) for x in pattern.fullmatch(tag).groups())


def app_dir(name: str) -> pathlib.Path:
    return APP if name == "beta" else STABLE_APP


def latest_tag() -> str:
    releases = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases?per_page=50"))
    tags = [r["tag_name"] for r in releases if not r.get("draft") and valid_tag(r["tag_name"])]
    if not tags:
        raise SystemExit("no new-line 0.x beta found")
    return max(tags, key=tag_order)


def receipt(tag: str) -> dict[str, str]:
    name = channel(tag)
    data = json.loads(asset(tag, "ftw-native-release.json"))
    if data.get("schema") != 1 or data.get("channel") != name or data.get("tag") != tag:
        raise SystemExit(f"{tag}: ftw-native-release.json does not describe this {name} release")
    sums = data.get("sha256") or {}
    for arch in ("amd64", "arm64"):
        want = sums.get(arch, "")
        if not HEX64.match(want):
            raise SystemExit(f"{tag}: receipt lacks a sha256 for {arch}")
        line = asset(tag, f"ftw-linux-{arch}.tar.gz.sha256").decode().split()
        if line != [want, f"ftw-linux-{arch}.tar.gz"]:
            raise SystemExit(f"{tag}: {arch} .sha256 file disagrees with the receipt")
    return {"amd64": sums["amd64"], "arm64": sums["arm64"]}


def manifest(directory: pathlib.Path) -> pathlib.Path:
    """config.yaml once the app is listed, else the unlisted manifest."""
    listed = directory / "config.yaml"
    return listed if listed.exists() else directory / UNLISTED


def field(text: str, key: str) -> str:
    m = re.search(rf'^ARG {key}=([^\n]*)$', text, re.M)
    if m is None:
        m = re.search(rf'^\s*{key}:\s*"?([^"\n]*)"?\s*$', text, re.M)
    if not m:
        raise SystemExit(f"missing {key}")
    return m.group(1).strip()


def read_pin(name: str = "beta") -> tuple[str | None, str | None, dict[str, str] | None]:
    """The pinned tag, app version and package sums; all None while unlisted."""
    directory = app_dir(name)
    path = manifest(directory)
    if (directory / "build.yaml").exists():
        raise SystemExit("keep the native pins in Dockerfile, not deprecated build.yaml")
    if path.name == UNLISTED and (name == "beta" or not path.exists()):
        raise SystemExit(f"{directory.name} has no config.yaml")
    if (directory / "config.yaml").exists() and (directory / UNLISTED).exists():
        raise SystemExit(f"{directory.name} must keep one manifest, not config.yaml and {UNLISTED}")
    config = path.read_text()
    build = (directory / "Dockerfile").read_text()
    if field(config, "slug") != SLUGS[name] or re.search(r"^image:", config, re.M):
        raise SystemExit(f"{directory.name} must keep slug {SLUGS[name]} and have no image: key (built on the device)")
    tag = field(build, "FTW_VERSION")
    version = field(config, "version")
    sums = {"amd64": field(build, "FTW_SHA256_AMD64"), "arm64": field(build, "FTW_SHA256_ARM64")}
    if path.name == UNLISTED:
        # Not in the store yet: no release is pinned, so nothing may look pinned.
        if tag or version or any(sums.values()) or field(config, "FTW_BUNDLE_VERSION") or field(config, "FTW_IMAGE_TAG"):
            raise SystemExit(f"{directory.name}/{UNLISTED} must pin nothing until the first stable")
        return None, None, None
    if channel(tag) != name:
        raise SystemExit(f"{directory.name} takes only {name} releases, not {tag}")
    if version != tag[1:] or field(config, "FTW_BUNDLE_VERSION") != version or field(config, "FTW_IMAGE_TAG") != tag:
        raise SystemExit("config.yaml and Dockerfile pin different versions")
    for arch, value in sums.items():
        if not HEX64.match(value):
            raise SystemExit(f"{directory.name} pins no sha256 for {arch}")
    return tag, version, sums


def put(text: str, key: str, pattern: str, value: str) -> str:
    """Set one pinned value; the line must be there exactly once."""
    out, count = re.subn(pattern, lambda m: m.group(1) + value, text, flags=re.M)
    if count != 1:
        raise SystemExit(f"expected one {key} line, found {count}")
    return out


def write_pin(tag: str, sums: dict[str, str]) -> None:
    name = channel(tag)
    read_pin(name)
    directory = app_dir(name)
    source = manifest(directory)
    version = tag[1:]
    config = source.read_text()
    if source.name == UNLISTED:
        config = re.sub(r"\A(?:#[^\n]*\n)+", "", config)  # the note about staying unlisted
    config = put(config, "version", r'^(version:[ \t]*)"[^"\n]*"[ \t]*$', f'"{version}"')
    config = put(config, "FTW_BUNDLE_VERSION", r'^([ \t]+FTW_BUNDLE_VERSION:[ \t]*)"[^"\n]*"[ \t]*$', f'"{version}"')
    config = put(config, "FTW_IMAGE_TAG", r'^([ \t]+FTW_IMAGE_TAG:[ \t]*)(?:""|\S*)[ \t]*$', tag)
    build = (directory / "Dockerfile").read_text()
    build = put(build, "FTW_VERSION", r"^(ARG FTW_VERSION=)\S*$", tag)
    build = put(build, "FTW_SHA256_AMD64", r"^(ARG FTW_SHA256_AMD64=)\S*$", sums["amd64"])
    build = put(build, "FTW_SHA256_ARM64", r"^(ARG FTW_SHA256_ARM64=)\S*$", sums["arm64"])
    (directory / "config.yaml").write_text(config)
    (directory / "Dockerfile").write_text(build)
    if source.name == UNLISTED:
        source.unlink()  # config.yaml now lists the app in the store


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        for name in ("beta", "stable"):
            if name == "stable" and not app_dir(name).is_dir():
                continue
            tag, _, sums = read_pin(name)
            if tag is None:
                print(f"ok: {SLUGS[name]} is not listed until the first 0.x stable")
                continue
            if receipt(tag) != sums:
                raise SystemExit(f"pinned sha256 values differ from {tag}'s receipt")
            print(f"ok: {SLUGS[name]} pins {tag}")
    elif cmd == "bump":
        tag = argv[2] if len(argv) > 2 else latest_tag()
        name = channel(tag)
        current, _, _ = read_pin(name)
        if current is not None and tag_order(tag) < tag_order(current):
            print(f"ignored older {name} {tag}; already pinned to {current}")
            return 0
        sums = receipt(tag)
        write_pin(tag, sums)
        if tag != current:
            changelog = app_dir(name) / "CHANGELOG.md"
            notes = changelog.read_text()
            entry = (f"# Changelog\n\n## {tag[1:]}\n\n"
                     f"- Update FTW to [{tag}](https://github.com/{REPO}/releases/tag/{tag}).\n")
            # App changes merged since the last pin ship with this one.
            if notes.startswith(UNRELEASED):
                notes = notes.replace(UNRELEASED, entry, 1)
            else:
                notes = notes.replace("# Changelog\n\n", entry + "\n", 1)
            changelog.write_text(notes)
        read_pin(name)
        print(f"pinned {tag}")
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
