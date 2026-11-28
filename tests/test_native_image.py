"""Offline tests for scripts/native_image.py: no registry, Docker or Cosign."""
import contextlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import native_image, native_pin

VERSION = "0.200.0-beta.1"
DIGESTS = {"amd64": "sha256:" + "d" * 64, "aarch64": "sha256:" + "c" * 64}
DIGEST = DIGESTS["amd64"]
RECIPE = "e" * 64
HEAD = "1" * 40


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class Registry:
    """A scripted registry behind `docker buildx imagetools`, `docker push` and `cosign`."""

    def __init__(self, images=None, signed=True, private=False, push_ok=True):
        self.images = dict(images or {})  # tag -> (digest, labels)
        self.signed, self.private, self.push_ok = signed, private, push_ok
        self.signatures = set()  # digests `cosign sign` signed here
        self.calls = []

    def labels(self, arch, version=VERSION, recipe=RECIPE, revision=HEAD):
        return {"io.hass.version": version, "io.hass.arch": arch, native_image.RECIPE_LABEL: recipe,
                native_image.REVISION_LABEL: revision}

    def add(self, arch, version=VERSION, **labels):
        self.images[native_image.ref(arch, version)] = (DIGESTS[arch], self.labels(arch, version, **labels))

    def __call__(self, *args):
        self.calls.append(args)
        if args[:3] == ("docker", "buildx", "imagetools"):
            reference, part = args[4], args[6]
            if self.private:
                return done(1, err="failed to fetch anonymous token: 403 Forbidden")
            found = self.images.get(reference)
            if found is None and "@" in reference:
                found = next((v for v in self.images.values() if reference.endswith(v[0])), None)
            if found is None:
                return done(1, err=f"ERROR: {reference}: not found")
            if part == "{{json .Manifest}}":
                return done(0, json.dumps({"digest": found[0]}))
            return done(0, json.dumps({"config": {"Labels": found[1]}}))
        if args[:2] == ("docker", "push"):
            if not self.push_ok:
                return done(1, err="denied")
            arch = next(a for a in native_image.ARCHES if f"/{a}-" in args[2])
            self.images[args[2]] = (DIGESTS[arch], self.labels(arch, args[2].rsplit(":", 1)[1]))
            return done()
        if args[:2] == ("cosign", "verify"):
            ok = self.signed or args[-1].rsplit("@", 1)[1] in self.signatures
            return done(0 if ok else 1, err="" if ok else "no matching signatures")
        if args[:2] == ("cosign", "sign"):
            self.signatures.add(args[-1].rsplit("@", 1)[1])
            return done()
        raise AssertionError(args)


class ImageTest(unittest.TestCase):
    def registry(self, **kwargs):
        registry = Registry(**kwargs)
        for patcher in (mock.patch.object(native_image, "run", side_effect=registry),
                        mock.patch.object(native_image.time, "sleep")):
            patcher.start()
            self.addCleanup(patcher.stop)
        return registry

    def test_the_tag_is_the_app_version_per_architecture(self):
        self.assertEqual(native_image.ref("aarch64", VERSION),
                         f"ghcr.io/srcfl/home-assistant-addons/aarch64-ftw-0x:{VERSION}")
        self.assertEqual(native_image.IMAGE, native_pin.IMAGE)
        for arch, version in (("arm64", VERSION), ("armv7", VERSION), ("amd64", "")):
            with self.subTest(arch=arch), self.assertRaises(native_image.ImageError):
                native_image.ref(arch, version)

    def test_signer_is_the_pin_workflow_on_main(self):
        workflow = pathlib.Path(".github/workflows/sync-native.yml")
        self.assertTrue((native_pin.ROOT / workflow).is_file())
        self.assertEqual(native_image.SIGNER,
                         f"https://github.com/srcfl/home-assistant-addons/{workflow.as_posix()}@refs/heads/main")

    def test_recipe_covers_what_the_image_is_built_from(self):
        with tempfile.TemporaryDirectory() as directory:
            app = pathlib.Path(directory) / "app"
            shutil.copytree(native_pin.APP, app)
            first = native_image.recipe_of(app)
            self.assertRegex(first, r"^[0-9a-f]{64}$")
            (app / "config.yaml").write_text("name: other\n")
            (app / "DOCS.md").write_text("other\n")
            self.assertEqual(native_image.recipe_of(app), first, "docs and the manifest are not in the image")
            for name in native_image.RECIPE:
                original = (app / name).read_bytes()
                (app / name).write_bytes(original + b"\n# change\n")
                with self.subTest(name=name):
                    self.assertNotEqual(native_image.recipe_of(app), first)
                (app / name).write_bytes(original)
            build = app / "Dockerfile"
            build.write_text(re.sub(r"(?m)^ARG FTW_SHA256_ARM64=.*$", f"ARG FTW_SHA256_ARM64={'0' * 64}",
                                    build.read_text()))
            self.assertNotEqual(native_image.recipe_of(app), first, "the pinned package is part of the recipe")

    def test_state_tells_absent_from_unreadable(self):
        registry = self.registry()
        self.assertIsNone(native_image.state("amd64", VERSION))
        registry.add("amd64")
        self.assertEqual(native_image.state("amd64", VERSION), DIGEST)
        registry.private = True
        with self.assertRaisesRegex(native_image.ImageError, "could not read"):
            native_image.state("amd64", VERSION)

    def test_push_never_overwrites_and_signs_the_pushed_digest(self):
        registry = self.registry()
        self.assertEqual(native_image.push("aarch64", VERSION), DIGESTS["aarch64"])
        tag = native_image.ref("aarch64", VERSION)
        self.assertIn(("docker", "push", tag), registry.calls)
        self.assertIn(("cosign", "sign", "--yes", native_image.digest_ref("aarch64", DIGESTS["aarch64"])),
                      registry.calls)
        registry.calls.clear()
        with self.assertRaisesRegex(native_image.ImageError, "never pushed twice"):
            native_image.push("aarch64", VERSION)
        self.assertFalse(any(call[:2] in (("docker", "push"), ("cosign", "sign")) for call in registry.calls))

    def test_first_push_to_a_package_that_does_not_exist_yet(self):
        # buildx's own words when neither the tag nor the package exists.
        registry = self.registry(signed=False)
        self.assertIsNone(native_image.state("amd64", VERSION))
        self.assertEqual(native_image.push("amd64", VERSION), DIGESTS["amd64"])
        self.assertIn(("docker", "push", native_image.ref("amd64", VERSION)), registry.calls)
        self.assertEqual(registry.signatures, {DIGESTS["amd64"]})

    def test_only_this_reference_not_found_means_absent(self):
        tag = native_image.ref("amd64", VERSION)
        for err in (f"ERROR: {tag}: not found", f"{tag}: not found\n", "manifest unknown",
                    'errors:\nname unknown: repository name not known to registry'):
            with self.subTest(err=err), mock.patch.object(native_image, "run", return_value=done(1, err=err)):
                self.assertIsNone(native_image.state("amd64", VERSION))
        for err in ('exec: "docker-buildx": executable file not found in $PATH',
                    "ERROR: failed to find driver: not found",
                    "ERROR: ghcr.io/srcfl/home-assistant-addons/amd64-ftw-0x:0.1.0-beta.1: not found",
                    f"ERROR: {tag}-rc: not found", "not found"):
            with self.subTest(err=err), mock.patch.object(native_image, "run", return_value=done(1, err=err)) as run:
                with self.assertRaisesRegex(native_image.ImageError, "could not read"):
                    native_image.state("amd64", VERSION)
                with self.assertRaisesRegex(native_image.ImageError, "could not read"):
                    native_image.push("amd64", VERSION)
                self.assertFalse(any(call.args[:2] == ("docker", "push") for call in run.mock_calls))

    def test_resume_signs_an_unsigned_image_of_this_pin(self):
        registry = self.registry(signed=False)
        registry.add("aarch64")
        self.assertEqual(native_image.resume("aarch64", VERSION, RECIPE, HEAD), DIGESTS["aarch64"])
        self.assertEqual(registry.signatures, {DIGESTS["aarch64"]})
        self.assertFalse(any(call[:2] == ("docker", "push") for call in registry.calls))
        registry.calls.clear()
        self.assertEqual(native_image.resume("aarch64", VERSION, RECIPE, HEAD), DIGESTS["aarch64"])
        self.assertFalse(any(call[:2] == ("cosign", "sign") for call in registry.calls), "signed once")

    def test_resume_refuses_an_image_from_another_build(self):
        for labels, wrong in ((dict(revision="2" * 40), "revision"), (dict(recipe="f" * 64), "recipe"),
                              (dict(version="0.199.0-beta.1"), "io.hass.version")):
            with self.subTest(wrong=wrong):
                registry = self.registry(signed=False)
                arch, version = "amd64", VERSION
                registry.images[native_image.ref(arch, version)] = (DIGESTS[arch], registry.labels(arch, **{
                    "version": labels.get("version", VERSION), "recipe": labels.get("recipe", RECIPE),
                    "revision": labels.get("revision", HEAD)}))
                with self.assertRaisesRegex(native_image.ImageError, f"unsigned and its .*{wrong}"):
                    native_image.resume(arch, VERSION, RECIPE, HEAD)
                self.assertEqual(registry.signatures, set())
        self.registry()
        with self.assertRaisesRegex(native_image.ImageError, "does not exist"):
            native_image.resume("amd64", VERSION, RECIPE, HEAD)

    def test_a_failed_push_signs_nothing(self):
        registry = self.registry(push_ok=False)
        with self.assertRaisesRegex(native_image.ImageError, "could not push"):
            native_image.push("amd64", VERSION)
        self.assertFalse(any(call[:2] == ("cosign", "sign") for call in registry.calls))

    def test_signing_is_retried_then_fails(self):
        with mock.patch.object(native_image, "run", return_value=done(1, err="rekor")) as run, \
                mock.patch.object(native_image.time, "sleep"), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(native_image.ImageError, "could not sign"):
                native_image.sign("ref@" + DIGEST)
        self.assertEqual(run.call_count, native_image.ATTEMPTS)

    def test_verify_accepts_public_signed_images_of_this_recipe(self):
        registry = self.registry()
        for arch in native_image.ARCHES:
            registry.add(arch)
        self.assertEqual(native_image.verify(VERSION, RECIPE), DIGESTS)
        verified = [call for call in registry.calls if call[:2] == ("cosign", "verify")]
        self.assertEqual(len(verified), len(native_image.ARCHES), "one verify per image, no retries")
        for call in verified:
            self.assertEqual(call[2:6], ("--certificate-identity", native_image.SIGNER,
                                         "--certificate-oidc-issuer", native_image.ISSUER))
            self.assertRegex(call[6], r"@sha256:[0-9a-f]{64}$", "verify the digest, not a tag that can move")

    def test_verify_refuses_what_users_could_not_safely_pull(self):
        cases = {
            "does not exist": dict(arches=("amd64",)),
            "without a login": dict(private=True),
            "no signature from the pin workflow": dict(signed=False),
            "labelled": dict(version="0.199.0-beta.1"),
            "another recipe": dict(recipe="f" * 64),
        }
        for message, case in cases.items():
            with self.subTest(message=message):
                registry = self.registry(signed=case.get("signed", True), private=case.get("private", False))
                for arch in case.get("arches", native_image.ARCHES):
                    registry.images[native_image.ref(arch, VERSION)] = (DIGESTS[arch], registry.labels(
                        arch, case.get("version", VERSION), case.get("recipe", RECIPE)))
                with self.assertRaisesRegex(native_image.ImageError, message):
                    native_image.verify(VERSION, RECIPE)

    def test_labels_of_a_multi_platform_index(self):
        index = {"linux/amd64": {"config": {"Labels": {"io.hass.arch": "amd64"}}},
                 "linux/arm64": {"config": {"Labels": {"io.hass.arch": "aarch64"}}}}
        with mock.patch.object(native_image, "run", return_value=done(0, json.dumps(index))):
            self.assertEqual(native_image.labels("aarch64", "x@" + DIGEST), {"io.hass.arch": "aarch64"})

    def test_verify_main_skips_an_app_built_on_the_device(self):
        with tempfile.TemporaryDirectory() as directory:
            app = pathlib.Path(directory) / "ftw-0x-beta"
            shutil.copytree(native_pin.APP, app)
            config = app / "config.yaml"
            text = config.read_text()
            version = native_pin.field(text, "version")
            with mock.patch.object(native_pin, "APP", app), \
                    mock.patch.object(native_pin, "STABLE_APP", pathlib.Path(directory) / "ftw-0x"), \
                    mock.patch.object(native_image, "verify") as verify, contextlib.redirect_stdout(io.StringIO()):
                config.write_text(re.sub(r"(?m)^image:.*\n", "", text))
                self.assertEqual(native_image.verify_main(), [])
                verify.assert_not_called()
                config.write_text(re.sub(r"(?m)^image:.*\n", "", text).replace(
                    f'version: "{version}"\n', f'version: "{version}"\n{native_pin.IMAGE_LINE}\n'))
                self.assertEqual(native_image.verify_main(), [version])
                verify.assert_called_once_with(version)

    def test_cli_prints_outputs_for_the_workflow(self):
        self.registry()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            native_image.main(["native_image.py", "state", "amd64", VERSION])
        self.assertEqual(out.getvalue(), "digest=\n")
        with self.assertRaises(SystemExit):
            native_image.main(["native_image.py", "push", "amd64"])


if __name__ == "__main__":
    unittest.main()
