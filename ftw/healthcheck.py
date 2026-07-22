#!/usr/bin/env python3
"""Check setup availability or Core readiness without gating on Optimizer."""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request


def get(path: str) -> bytes:
    request = urllib.request.Request(
        f"http://127.0.0.1:8080{path}",
        headers={"User-Agent": "ftw-home-assistant-healthcheck"},
    )
    with urllib.request.urlopen(request, timeout=4) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return response.read()


def main() -> int:
    try:
        if not pathlib.Path("/data/config.yaml").is_file():
            get("/setup")
            return 0
        payload = json.loads(get("/api/status"))
        if not isinstance(payload, dict):
            raise ValueError("/api/status did not return a JSON object")
        return 0
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
        print(f"FTW Core is not ready: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
