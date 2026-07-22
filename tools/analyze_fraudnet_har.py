"""一次性 HAR 分析脚本：从一次成功的 PayPal SignUp HAR 里提取 fraudnet / magnes /
device fingerprint 相关的请求，找出协议模式缺失的"build cmid record"那一步。

用法：
    python tools/analyze_fraudnet_har.py <path-to-har>

输出：列出所有"看起来像 fraudnet collect"的请求（按时间顺序），含 method/url/
请求体片段。

启发式：URL 含 magnes / fraudnet / dyson / b\.stats\.paypal / c\.paypal / counter
/ tagmanager / tracking 之类的关键字；或 POST 到 paypal.com 但不属于 graphql /
checkoutweb / hermes / api 这种已知主链路。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 已知与 fraudnet / device fingerprint / risk 相关的 URL pattern
FRAUDNET_PATTERNS = [
    r"magnes",
    r"fraudnet",
    r"dyson",
    r"b\.stats\.paypal",
    r"c\.paypal\.com",
    r"counter\.cgi",
    r"tagmanager",
    r"/tracking",
    r"clientmetadataid",
    r"/r/fb",
    r"/track/",
]
FRAUDNET_RE = re.compile("|".join(FRAUDNET_PATTERNS), re.IGNORECASE)

# 主链路 URL：见过这些就跳过
MAIN_PATH_PATTERNS = [
    r"/checkoutweb/",
    r"/agreements/approve",
    r"/api/",
    r"/graphql",
    r"/hermes",
    r"/idapps/",
    r"\.css",
    r"\.svg",
    r"\.png",
    r"\.woff",
    r"\.ttf",
    r"\.ico",
    r"\.gif",
    r"\.jpg",
    r"google-analytics",
    r"googletagmanager",
    r"doubleclick",
    r"hotjar",
]
MAIN_PATH_RE = re.compile("|".join(MAIN_PATH_PATTERNS), re.IGNORECASE)


def main(har_path: str) -> None:
    p = Path(har_path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    har = json.loads(raw)

    entries = har.get("log", {}).get("entries", [])
    print(f"HAR 总请求数: {len(entries)}")

    fraudnet_hits: list[dict] = []
    paypal_unknown: list[dict] = []
    paypal_post: list[dict] = []

    for ent in entries:
        req = ent.get("request") or {}
        url = req.get("url") or ""
        method = req.get("method") or ""

        # 1) 直接命中 fraudnet pattern
        if FRAUDNET_RE.search(url):
            fraudnet_hits.append(ent)
            continue

        # 2) 在 paypal.com 上但不在主链路（可能是隐藏的 risk / tracking）
        if "paypal.com" in url.lower() and not MAIN_PATH_RE.search(url):
            paypal_unknown.append(ent)

        # 3) 所有 POST 到 paypal 的请求（备查）
        if method.upper() == "POST" and "paypal.com" in url.lower():
            paypal_post.append(ent)

    print(f"\n=== Fraudnet 直接命中: {len(fraudnet_hits)} 条 ===")
    for ent in fraudnet_hits[:50]:
        _dump_entry(ent)

    print(f"\n=== paypal.com 上非主链路（潜在 risk / tracking）: {len(paypal_unknown)} 条 ===")
    seen_urls: set[str] = set()
    for ent in paypal_unknown:
        url = ent.get("request", {}).get("url", "")
        # URL 去重（query 不同当成不同；但同 path+method 只展示首条）
        sig = (
            ent.get("request", {}).get("method", ""),
            url.split("?", 1)[0],
        )
        if sig in seen_urls:
            continue
        seen_urls.add(sig)
        _dump_entry(ent)

    print(f"\n=== POST 到 paypal.com 全集: {len(paypal_post)} 条（去重 path）===")
    seen_post: set[tuple[str, str]] = set()
    for ent in paypal_post:
        url = ent.get("request", {}).get("url", "")
        path = url.split("?", 1)[0]
        sig = ("POST", path)
        if sig in seen_post:
            continue
        seen_post.add(sig)
        print(f"  POST {path}")


def _dump_entry(ent: dict) -> None:
    req = ent.get("request") or {}
    url = req.get("url", "")
    method = req.get("method", "")
    started = ent.get("startedDateTime", "")
    headers = {h.get("name", "").lower(): h.get("value", "") for h in (req.get("headers") or [])}
    ct = headers.get("content-type", "")
    post_data = req.get("postData") or {}
    text = post_data.get("text") or ""

    print(f"\n--- {started}")
    print(f"  {method} {url[:240]}")
    if ct:
        print(f"  Content-Type: {ct}")
    if text:
        preview = text if len(text) <= 800 else text[:800] + "…"
        # 单行显示，把换行替换掉
        preview_oneline = preview.replace("\n", " ").replace("\r", "")
        print(f"  Body: {preview_oneline}")

    # Response status / 关键 header
    resp = ent.get("response") or {}
    status = resp.get("status", "")
    resp_headers = {h.get("name", "").lower(): h.get("value", "") for h in (resp.get("headers") or [])}
    set_cookie = resp_headers.get("set-cookie", "")
    print(f"  → status={status}" + (f"  set-cookie={set_cookie[:200]}…" if set_cookie else ""))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_fraudnet_har.py <har-path>")
        sys.exit(1)
    main(sys.argv[1])
