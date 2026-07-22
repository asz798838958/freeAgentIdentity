"""
HAR 文件自动分析工具 — 解析认证流程，输出结构化报告。

用法:
    python3 tools/har_analyze.py --file tools/captures/example.har

    # 输出 markdown 报告
    python3 tools/har_analyze.py --file tools/captures/example.har --output report.md

    # 只看认证相关请求
    python3 tools/har_analyze.py --file tools/captures/example.har --auth-only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote


# 认证相关 URL 关键词
AUTH_KEYWORDS = {
    "auth", "login", "signin", "sign-in", "signup", "sign-up", "register",
    "oauth", "authorize", "callback", "token", "session", "csrf",
    "otp", "verify", "verification", "password", "mfa", "2fa",
    "sentinel", "challenge", "captcha", "turnstile",
    "account", "user", "profile", "me",
}

# 敏感 header
AUTH_HEADERS = {
    "authorization", "cookie", "set-cookie", "x-csrf-token",
    "openai-sentinel-token", "x-api-key", "x-auth-token",
}


def load_har(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_auth_related(url: str, method: str, req_headers: dict, resp_headers: dict) -> bool:
    """判断请求是否与认证相关"""
    url_lower = url.lower()

    # URL 包含认证关键词
    if any(kw in url_lower for kw in AUTH_KEYWORDS):
        return True

    # POST 请求通常更重要
    if method == "POST":
        return True

    # 设置 cookie 的请求
    for h in resp_headers:
        if h.get("name", "").lower() == "set-cookie":
            return True

    # 包含认证 header
    for h in req_headers:
        if h.get("name", "").lower() in AUTH_HEADERS:
            return True

    return False


def extract_redirects(entries: list) -> list[dict]:
    """提取重定向链"""
    redirects = []
    for entry in entries:
        status = entry["response"]["status"]
        if status in (301, 302, 303, 307, 308):
            location = ""
            for h in entry["response"]["headers"]:
                if h["name"].lower() == "location":
                    location = h["value"]
            redirects.append({
                "from": entry["request"]["url"],
                "to": location,
                "status": status,
            })
    return redirects


def extract_cookies(entries: list) -> dict[str, list]:
    """提取所有 Set-Cookie"""
    cookies = defaultdict(list)
    for entry in entries:
        url = entry["request"]["url"]
        domain = urlparse(url).netloc
        for h in entry["response"]["headers"]:
            if h["name"].lower() == "set-cookie":
                cookie_str = h["value"]
                name = cookie_str.split("=")[0].strip()
                cookies[domain].append(name)
    return dict(cookies)


def extract_js_files(entries: list) -> list[dict]:
    """提取加载的 JS 文件"""
    js_files = []
    for entry in entries:
        url = entry["request"]["url"]
        content_type = ""
        for h in entry["response"]["headers"]:
            if h["name"].lower() == "content-type":
                content_type = h["value"]
        if "javascript" in content_type or url.endswith(".js"):
            size = entry["response"]["content"].get("size", 0)
            js_files.append({"url": url, "size": size})
    return js_files


def detect_anti_bot(entries: list, js_files: list) -> list[str]:
    """检测反爬机制"""
    mechanisms = []

    all_urls = [e["request"]["url"] for e in entries]
    all_urls_str = " ".join(all_urls)

    # Cloudflare
    if any("challenges.cloudflare.com" in u for u in all_urls):
        mechanisms.append("Cloudflare Turnstile")
    if any("cf-challenge" in u.lower() for u in all_urls):
        mechanisms.append("Cloudflare Challenge")

    # reCAPTCHA
    if any("google.com/recaptcha" in u for u in all_urls):
        mechanisms.append("Google reCAPTCHA")

    # hCaptcha
    if any("hcaptcha.com" in u for u in all_urls):
        mechanisms.append("hCaptcha")

    # Sentinel (OpenAI)
    if any("sentinel" in u.lower() for u in all_urls):
        mechanisms.append("OpenAI Sentinel (PoW + Turnstile)")

    # Custom PoW
    for entry in entries:
        body = entry["response"]["content"].get("text", "")
        if "proofofwork" in body.lower() or "proof-of-work" in body.lower():
            mechanisms.append("Proof of Work")
            break

    # Fingerprint JS
    for js in js_files:
        if "fingerprint" in js["url"].lower():
            mechanisms.append(f"Fingerprint JS: {js['url'][:80]}")

    return mechanisms


def detect_auth_pattern(entries: list) -> str:
    """检测认证模式"""
    all_urls = [e["request"]["url"] for e in entries]

    patterns = []
    if any("oauth" in u.lower() or "authorize" in u.lower() for u in all_urls):
        patterns.append("OAuth 2.0")
    if any("openid" in u.lower() for u in all_urls):
        patterns.append("OpenID Connect")
    if any("/token" in u.lower() for u in all_urls):
        patterns.append("Token Exchange")

    for entry in entries:
        for h in entry["response"]["headers"]:
            if h["name"].lower() == "set-cookie" and "session" in h["value"].lower():
                if "Session Cookie" not in patterns:
                    patterns.append("Session Cookie")

    for entry in entries:
        for h in entry["request"]["headers"]:
            if h["name"].lower() == "authorization" and "bearer" in h["value"].lower():
                if "Bearer Token (JWT)" not in patterns:
                    patterns.append("Bearer Token (JWT)")

    return ", ".join(patterns) if patterns else "Unknown"


def analyze_har(har_data: dict, auth_only: bool = False) -> dict:
    """分析 HAR 文件，返回结构化报告"""
    entries = har_data.get("log", {}).get("entries", [])

    # 基本信息
    domains = set()
    for entry in entries:
        domains.add(urlparse(entry["request"]["url"]).netloc)

    # 过滤认证相关请求
    auth_entries = []
    for entry in entries:
        req = entry["request"]
        resp = entry["response"]
        url = req["url"]
        method = req["method"]

        if auth_only and not is_auth_related(url, method, req["headers"], resp["headers"]):
            continue

        # 解析请求体
        post_data = ""
        if req.get("postData"):
            post_data = req["postData"].get("text", "")

        # 解析响应体
        resp_body = resp.get("content", {}).get("text", "")

        # 提取关键响应头
        resp_cookies = []
        resp_location = ""
        for h in resp["headers"]:
            name_lower = h["name"].lower()
            if name_lower == "set-cookie":
                resp_cookies.append(h["value"].split(";")[0])
            elif name_lower == "location":
                resp_location = h["value"]

        auth_entries.append({
            "url": url,
            "method": method,
            "status": resp["status"],
            "post_data": post_data[:500] if post_data else "",
            "resp_body_preview": resp_body[:500] if resp_body else "",
            "resp_cookies": resp_cookies,
            "resp_location": resp_location,
            "content_type": next(
                (h["value"] for h in resp["headers"] if h["name"].lower() == "content-type"), ""
            ),
        })

    # 分析结果
    redirects = extract_redirects(entries)
    cookies = extract_cookies(entries)
    js_files = extract_js_files(entries)
    anti_bot = detect_anti_bot(entries, js_files)
    auth_pattern = detect_auth_pattern(entries)

    return {
        "total_requests": len(entries),
        "auth_requests": len(auth_entries),
        "domains": sorted(domains),
        "auth_pattern": auth_pattern,
        "anti_bot": anti_bot,
        "redirects": redirects,
        "cookies": cookies,
        "js_files": [j for j in js_files if j["size"] > 10000],  # 只列大文件
        "entries": auth_entries,
    }


def format_report(report: dict, format: str = "text") -> str:
    """格式化分析报告"""
    lines = []

    lines.append("=" * 70)
    lines.append("HAR 认证流程分析报告")
    lines.append("=" * 70)

    lines.append(f"\n## 概览")
    lines.append(f"  总请求数: {report['total_requests']}")
    lines.append(f"  认证相关: {report['auth_requests']}")
    lines.append(f"  域名: {', '.join(report['domains'])}")
    lines.append(f"  认证模式: {report['auth_pattern']}")

    if report["anti_bot"]:
        lines.append(f"\n## 反爬机制")
        for m in report["anti_bot"]:
            lines.append(f"  - {m}")

    if report["cookies"]:
        lines.append(f"\n## Cookie 设置")
        for domain, names in report["cookies"].items():
            unique = sorted(set(names))
            lines.append(f"  {domain}: {', '.join(unique)}")

    if report["redirects"]:
        lines.append(f"\n## 重定向链 ({len(report['redirects'])} 个)")
        for r in report["redirects"][:20]:
            from_short = urlparse(r["from"]).path[:50]
            to_short = r["to"][:60]
            lines.append(f"  {r['status']} {from_short} → {to_short}")

    lines.append(f"\n## 认证请求链 ({report['auth_requests']} 个)")
    lines.append("-" * 70)

    for i, entry in enumerate(report["entries"], 1):
        parsed = urlparse(entry["url"])
        path = parsed.path
        if parsed.query:
            # 只显示关键参数
            params = parse_qs(parsed.query)
            key_params = {k: v[0][:30] for k, v in params.items()
                         if k in ("client_id", "redirect_uri", "response_type", "scope", "state", "code", "grant_type")}
            if key_params:
                path += "?" + "&".join(f"{k}={v}" for k, v in key_params.items())

        lines.append(f"\n### [{i}] {entry['method']} {entry['status']} {parsed.netloc}{path}")

        if entry["post_data"]:
            # 尝试格式化 JSON
            try:
                pd = json.loads(entry["post_data"])
                lines.append(f"  Body: {json.dumps(pd, ensure_ascii=False, indent=2)[:300]}")
            except json.JSONDecodeError:
                lines.append(f"  Body: {entry['post_data'][:200]}")

        if entry["resp_location"]:
            lines.append(f"  Location: {entry['resp_location'][:100]}")

        if entry["resp_cookies"]:
            lines.append(f"  Set-Cookie: {'; '.join(entry['resp_cookies'][:3])}")

        if entry["resp_body_preview"]:
            try:
                rb = json.loads(entry["resp_body_preview"])
                # 只显示顶层 key
                if isinstance(rb, dict):
                    lines.append(f"  Response keys: {list(rb.keys())[:10]}")
                    # 如果有 page/type 字段，突出显示
                    if "page" in rb and isinstance(rb["page"], dict):
                        lines.append(f"  page.type: {rb['page'].get('type', '?')}")
                    if "url" in rb:
                        lines.append(f"  url: {str(rb['url'])[:100]}")
            except json.JSONDecodeError:
                if len(entry["resp_body_preview"]) < 200:
                    lines.append(f"  Response: {entry['resp_body_preview'][:200]}")

    if report["js_files"]:
        lines.append(f"\n## 大 JS 文件 (>10KB)")
        for js in report["js_files"][:10]:
            lines.append(f"  {js['size'] / 1024:.0f}KB  {js['url'][:80]}")

    lines.append(f"\n{'=' * 70}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="HAR 文件分析工具")
    parser.add_argument("--file", required=True, help="HAR 文件路径")
    parser.add_argument("--output", help="输出报告文件路径")
    parser.add_argument("--auth-only", action="store_true", help="只显示认证相关请求")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--strict", action="store_true", help="严格模式：只显示核心认证请求")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"文件不存在: {args.file}")
        sys.exit(1)

    har_data = load_har(args.file)
    report = analyze_har(har_data, auth_only=args.auth_only)

    if args.strict:
        # 严格过滤：只保留核心认证请求
        NOISE_PATTERNS = {
            "/ces/", "/analytics", "/telemetry", "/track", "/rgstr",
            "/settings/", "/memories", "/onboarding", "/announcement",
            "/backend-api/apps", "/backend-api/conversation",
            "/backend-api/models", "/backend-api/prompt",
            "google.com", "googleapis.com", "immersivetranslate",
            ".js", ".css", ".png", ".jpg", ".svg", ".woff", ".ico",
            "challenge-platform/scripts", "challenge-platform/h/b/jsd",
        }
        KEEP_PATTERNS = {
            "authorize", "callback", "signin", "signup", "register",
            "login", "token", "session", "csrf", "otp", "verify",
            "sentinel/req", "sentinel/frame", "sentinel/sdk",
            "create_account", "create-account", "password",
            "client_auth_session_dump", "email-otp",
        }
        filtered = []
        for entry in report["entries"]:
            url_lower = entry["url"].lower()
            # 跳过噪音
            if any(p in url_lower for p in NOISE_PATTERNS):
                # 但如果匹配 KEEP_PATTERNS 则保留
                if not any(p in url_lower for p in KEEP_PATTERNS):
                    continue
            # 保留重定向
            if entry["status"] in (301, 302, 303, 307, 308):
                filtered.append(entry)
                continue
            # 保留认证关键请求
            if any(p in url_lower for p in KEEP_PATTERNS):
                filtered.append(entry)
                continue
            # 保留 POST 到 auth 域名
            if entry["method"] == "POST" and any(d in url_lower for d in ("auth.", "sentinel.")):
                filtered.append(entry)
                continue
        report["entries"] = filtered
        report["auth_requests"] = len(filtered)

    if args.json:
        output = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        output = format_report(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"✓ 报告已保存: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
