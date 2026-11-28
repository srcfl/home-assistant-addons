#!/usr/bin/env python3
"""The prebuilt 0.x app images that Supervisor pulls.

  native_image.py ref ARCH VERSION     print the image tag for one architecture
  native_image.py recipe DIR           print the recipe digest of an app folder
  native_image.py state ARCH VERSION   print digest=<digest>, or digest= when
                                       the tag does not exist
  native_image.py push ARCH VERSION    push the local image to a tag that does
                                       not exist yet, then sign the pushed digest
  native_image.py resume ARCH VERSION RECIPE HEAD
                                       sign an image an earlier run pushed but
                                       did not sign, if its labels show it was
                                       built from this recipe and commit
  native_image.py verify VERSION [RECIPE]
                                       check every architecture's image for
                                       VERSION before a pin merges
  native_image.py verify-main          check the images of the versions main pins

Each FTW release gets one image per architecture, tagged with the app version
and never pushed twice. Both apps pull the same image for the same release,
since validate.py keeps their recipes equal. Supervisor checks no signature,
so the pin workflow checks it before the merge that lets users see a version.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import time

if __package__:
    from . import native_pin
else:
    import native_pin

IMAGE = native_pin.IMAGE
ARCHES = ("amd64", "aarch64")
PLATFORMS = {"amd64": "linux/amd64", "aarch64": "linux/arm64"}
# The files the Dockerfile copies, plus the Dockerfile and its pins. Equal
# digests build the same app.
RECIPE = ("Dockerfile", "run.sh", "healthcheck.sh", "mqtt-service.sh")
RECIPE_LABEL = "com.sourceful.ftw.recipe"
REVISION_LABEL = "org.opencontainers.image.revision"
# Keyless Cosign identity of the pin workflow, as it runs from main.
SIGNER = ("https://github.com/srcfl/home-assistant-addons/"
          ".github/workflows/sync-native.yml@refs/heads/main")
ISSUER = "https://token.actions.githubusercontent.com"
# The Cosign release every workflow installs; RELEASING.md names it too.
COSIGN = "v3.0.6"
# The registry's own errors for a missing tag or package.
ABSENT = ("manifest unknown", "name unknown")
ATTEMPTS = 3


class ImageError(ValueError):
    pass


def ref(arch: str, version: str) -> str:
    if arch not in ARCHES:
        raise ImageError(f"no image for {arch}")
    if not version:
        raise ImageError("an image needs a version")
    return f"{IMAGE.format(arch=arch)}:{version}"


def digest_ref(arch: str, digest: str) -> str:
    return f"{IMAGE.format(arch=arch)}@{digest}"


def recipe(read) -> str:
    """One digest over the recipe files, given read(name) -> bytes."""
    total = hashlib.sha256()
    for name in RECIPE:
        total.update(f"{name}\0{hashlib.sha256(read(name)).hexdigest()}\n".encode())
    return total.hexdigest()


def recipe_of(directory: pathlib.Path) -> str:
    return recipe(lambda name: (directory / name).read_bytes())


def recipe_at(commit: str, directory: str) -> str:
    return recipe(lambda name: subprocess.check_output(["git", "show", f"{commit}:{directory}/{name}"]))


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def absent(reference: str, result: subprocess.CompletedProcess[str]) -> bool:
    """Whether a failed inspect means that reference does not exist.

    buildx reports a missing tag, or a package nobody has pushed to yet, as
    "ERROR: <reference>: not found". Only that line for this exact reference,
    or the registry's own error, counts: a "not found" about anything else (a
    missing program, builder or file) must not read as "push a new tag".
    """
    detail = f"{result.stdout}\n{result.stderr}"
    if any(marker in detail.lower() for marker in ABSENT):
        return True
    return any(line.strip().removeprefix("ERROR: ") == f"{reference}: not found" for line in detail.splitlines())


def inspect(reference: str, part: str) -> dict | None:
    """The registry's manifest or image config for reference; None when absent."""
    result = run("docker", "buildx", "imagetools", "inspect", reference, "--format", f"{{{{json .{part}}}}}")
    if result.returncode == 0:
        return json.loads(result.stdout)
    if absent(reference, result):
        return None
    raise ImageError(f"could not read {reference}: {(result.stderr or result.stdout).strip()}")


def state(arch: str, version: str) -> str | None:
    """The digest the tag points at, or None when the tag does not exist."""
    manifest = inspect(ref(arch, version), "Manifest")
    if manifest is None:
        return None
    digest = str(manifest.get("digest", ""))
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ImageError(f"{ref(arch, version)} has no valid digest")
    return digest


def labels(arch: str, reference: str) -> dict[str, str]:
    config = inspect(reference, "Image")
    if config is None:
        raise ImageError(f"{reference} has no image config")
    if "config" not in config:  # an index: one config per platform
        config = config.get(PLATFORMS[arch]) or {}
    return dict((config.get("config") or {}).get("Labels") or {})


def sign(reference: str) -> None:
    for attempt in range(1, ATTEMPTS + 1):
        result = run("cosign", "sign", "--yes", reference)
        if result.returncode == 0:
            return
        print(f"cosign sign {reference}: attempt {attempt} failed\n{result.stderr.strip()}", file=sys.stderr)
        if attempt < ATTEMPTS:
            time.sleep(5 * attempt)
    raise ImageError(f"could not sign {reference}")


def signed(reference: str) -> None:
    """The pin workflow's keyless signature is on reference, or ImageError."""
    for attempt in range(1, ATTEMPTS + 1):
        result = run("cosign", "verify", "--certificate-identity", SIGNER,
                     "--certificate-oidc-issuer", ISSUER, reference)
        if result.returncode == 0:
            return
        if attempt < ATTEMPTS:  # Sigstore's services fail now and then
            time.sleep(5 * attempt)
    raise ImageError(f"{reference} has no signature from the pin workflow on main: {result.stderr.strip()}")


def push(arch: str, version: str) -> str:
    """Push the local image once, then sign the digest the registry holds."""
    tag = ref(arch, version)
    if state(arch, version) is not None:
        raise ImageError(f"{tag} exists; a version is never pushed twice")
    result = run("docker", "push", tag)
    if result.returncode != 0:
        raise ImageError(f"could not push {tag}: {result.stderr.strip()}")
    digest = state(arch, version)
    if digest is None:
        raise ImageError(f"{tag} is missing after the push")
    sign(digest_ref(arch, digest))
    return digest


def resume(arch: str, version: str, want_recipe: str, head: str) -> str:
    """Finish an image that an earlier run pushed but did not sign.

    A run can push and then fail to sign; the re-run finds the tag and must
    not push again. It signs that digest only if the labels the build step
    wrote show this version, CPU, recipe and pin commit.
    """
    tag = ref(arch, version)
    digest = state(arch, version)
    if digest is None:
        raise ImageError(f"{tag} does not exist")
    pinned = digest_ref(arch, digest)
    try:
        signed(pinned)
        return digest
    except ImageError:
        pass
    found = labels(arch, pinned)
    want = {"io.hass.version": version, "io.hass.arch": arch, RECIPE_LABEL: want_recipe, REVISION_LABEL: head}
    wrong = sorted(key for key, value in want.items() if found.get(key) != value)
    if wrong:
        raise ImageError(f"{tag} is unsigned and its {', '.join(wrong)} do not match this pin; "
                         "delete that package version, then re-run")
    sign(pinned)
    return digest


def verify(version: str, want_recipe: str | None = None) -> dict[str, str]:
    """Every architecture's image for version, as Supervisor will pull it.

    Run this without a registry login: an image that only a login can read
    does not reach users. Checks the labels the pin workflow wrote and the
    pin workflow's keyless Cosign signature on the exact digest.
    """
    digests = {}
    for arch in ARCHES:
        tag = ref(arch, version)
        try:
            digest = state(arch, version)
        except ImageError as error:
            raise ImageError(f"{tag} cannot be pulled without a login; is the package public? {error}") from error
        if digest is None:
            raise ImageError(f"{tag} does not exist; the pin workflow builds it before the merge")
        pinned = digest_ref(arch, digest)
        found = labels(arch, pinned)
        if found.get("io.hass.version") != version or found.get("io.hass.arch") != arch:
            raise ImageError(f"{tag} is labelled {found.get('io.hass.version')} for {found.get('io.hass.arch')}")
        if want_recipe is not None and found.get(RECIPE_LABEL) != want_recipe:
            raise ImageError(f"{tag} was built from another recipe than the commit that would merge")
        signed(pinned)
        digests[arch] = digest
    return digests


def verify_main() -> list[str]:
    """Check each listed app that names an image; return what was checked."""
    checked = []
    for name in ("beta", "stable"):
        config = native_pin.app_dir(name) / "config.yaml"
        if not config.exists():
            continue
        text = config.read_text()
        version = native_pin.field(text, "version")
        if native_pin.image(text) is None:
            print(f"{native_pin.SLUGS[name]} {version} builds on the device; the next pin adds its image")
            continue
        verify(version)
        print(f"ok: {native_pin.SLUGS[name]} {version} has public, signed images for {' and '.join(ARCHES)}")
        checked.append(version)
    return checked


def main(argv: list[str]) -> int:
    cmd, args = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
    if cmd == "ref" and len(args) == 2:
        print(ref(*args))
    elif cmd == "recipe" and len(args) == 1:
        print(recipe_of(pathlib.Path(args[0])))
    elif cmd == "state" and len(args) == 2:
        print(f"digest={state(*args) or ''}")
    elif cmd == "push" and len(args) == 2:
        print(f"digest={push(*args)}")
    elif cmd == "resume" and len(args) == 4:
        print(f"digest={resume(*args)}")
    elif cmd == "verify" and len(args) in (1, 2):
        for arch, digest in verify(*args).items():
            print(f"ok: {ref(arch, args[0])} {digest}")
    elif cmd == "verify-main" and not args:
        verify_main()
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except ImageError as error:
        raise SystemExit(f"native_image: {error}") from error
