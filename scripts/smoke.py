#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api"
    endpoints = [
        f"{base}/health",
        f"{base}/ready",
        f"{base}/platforms",
        f"{base}/config",
        f"{base}/tasks",
        f"{base}/tasks/logs",
        f"{base}/proxies",
    ]
    failed = False
    for url in endpoints:
        try:
            data = fetch(url)
            label = list(data)[:5] if isinstance(data, dict) else type(data).__name__
            print(f"[OK] {url} -> {label}")
        except urllib.error.URLError as exc:
            failed = True
            print(f"[FAIL] {url} -> {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
