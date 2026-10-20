"""Offline tests for scripts/native_pin.py (no network)."""
import json
import shutil
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import native_pin  # noqa: E402

A = "a" * 64
B = "b" * 64


def fake_assets(tag, amd=A, arm=B, sha_arm=None):
    files = {
        "ftw-native-release.json": json.dumps(
            {"schema": 1, "channel": "beta", "tag": tag, "sha256": {"amd64": amd, "arm64": arm}}
        ).encode(),
        "ftw-linux-amd64.tar.gz.sha256": f"{amd}  ftw-linux-amd64.tar.gz\n".encode(),
        "ftw-linux-arm64.tar.gz.sha256": f"{sha_arm or arm}  ftw-linux-arm64.tar.gz\n".encode(),
    }
    return lambda t, name: files[name]


@pytest.fixture
def app(tmp_path, monkeypatch):
    shutil.copytree(native_pin.APP, tmp_path / "ftw-0x-beta")
    monkeypatch.setattr(native_pin, "APP", tmp_path / "ftw-0x-beta")
    return tmp_path / "ftw-0x-beta"


def test_receipt_accepts_matching_sums(monkeypatch):
    monkeypatch.setattr(native_pin, "asset", fake_assets("v0.160.0-beta.1"))
    assert native_pin.receipt("v0.160.0-beta.1") == {"amd64": A, "arm64": B}


def test_receipt_rejects_sha_file_mismatch(monkeypatch):
    monkeypatch.setattr(native_pin, "asset", fake_assets("v0.160.0-beta.1", sha_arm="c" * 64))
    with pytest.raises(SystemExit, match="disagrees"):
        native_pin.receipt("v0.160.0-beta.1")


def test_receipt_rejects_wrong_tag(monkeypatch):
    monkeypatch.setattr(native_pin, "asset", fake_assets("v0.160.0-beta.2"))
    with pytest.raises(SystemExit, match="does not describe"):
        native_pin.receipt("v0.160.0-beta.1")


@pytest.mark.parametrize("tag", ["v0.130.0-beta.1", "v3.8.0-beta.1", "v0.160.0", "latest"])
def test_old_line_and_stable_tags_are_refused(tag):
    with pytest.raises(SystemExit, match="not a new-line"):
        native_pin.receipt(tag)


def test_bump_rewrites_both_files(app, monkeypatch):
    monkeypatch.setattr(native_pin, "asset", fake_assets("v0.160.0-beta.1"))
    native_pin.main(["x", "bump", "v0.160.0-beta.1"])
    tag, version, sums = native_pin.read_pin()
    assert (tag, version, sums) == ("v0.160.0-beta.1", "0.160.0-beta.1", {"amd64": A, "arm64": B})
    native_pin.main(["x", "check"])


def test_image_key_is_refused(app):
    (app / "config.yaml").write_text((app / "config.yaml").read_text() + "image: ghcr.io/x/y\n")
    with pytest.raises(SystemExit, match="no image"):
        native_pin.read_pin()
