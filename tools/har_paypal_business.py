"""PayPal 业务调用快照：剔除 _next 静态资源、tealeaf 遥测、observability 等噪声，
只保留 graphql / auth / pay / checkoutweb / agreements 这些有协议含义的端点。"""
from __future__ import annotations

import json
import pathlib
import sys
from urllib.parse import urlparse


BUSINESS_PATH_PREFIXES = (
    "/checkoutweb/",
    "/checksiteconfig",
    "/auth/verifygrcenterprise",
    "/auth/verifyhcaptchapassive",
    "/auth/validatecaptcha",
    "/getcaptcha/",
    "/idapps/graphql",
    "/graphql",
    "/pay",
    "/agreements/",
    "/webapps/hermes",
)


def is_business(path: str) -> bool:
    # 排除 /pay/_next 等静态资源
    if path.startswith("/pay/_next") or path.startswith("/pay/api/trpc/observability"):
        return False
    return any(path.startswith(prefix) for prefix in BUSINESS_PATH_PREFIXES)


def main(har_path: str, out_path: str) -> None:
    data = json.loads(pathlib.Path(har_path).read_bytes())
    entries = data["log"]["entries"]
    out: list[str] = []

    def w(line: str = "") -> None:
        out.append(line)

    for idx, entry in enumerate(entries):
        url = entry["request"]["url"]
        host = (urlparse(url).hostname or "").lower()
        path = urlparse(url).path
        if "paypal.com" not in host:
            continue
        if not is_business(path):
            continue

        method = entry["request"]["method"]
        status = entry["response"]["status"]
        w("=" * 100)
        w(f"[{idx}] {method} {url}")
        w(f"  status: {status}")

        req_headers = {h["name"]: h["value"] for h in entry["request"]["headers"]}
        important = (
            "Origin", "Referer", "Content-Type", "Accept", "Accept-Language",
            "x-csrf-token", "paypal-client-context", "x-paypal-client-metadata-id",
            "x-paypal-internal-context", "x-requested-with",
        )
        for key in important:
            for k, v in req_headers.items():
                if k.lower() == key.lower():
                    if len(v) > 200:
                        w(f"  req.{key}: {v[:200]}...({len(v)} chars)")
                    else:
                        w(f"  req.{key}: {v}")
        if "Cookie" in req_headers:
            cookies = [c.strip().split("=")[0] for c in req_headers["Cookie"].split(";") if c.strip()]
            w(f"  req.Cookie: ({len(cookies)} cookies) {', '.join(cookies[:10])}{'...' if len(cookies) > 10 else ''}")

        post = entry["request"].get("postData") or {}
        text = post.get("text") or ""
        mime = post.get("mimeType") or ""
        if text:
            w(f"  req.body[{mime}] ({len(text)} chars):")
            limit = 3000
            if len(text) <= limit:
                w("    " + text.replace("\n", "\n    "))
            else:
                w("    " + text[:limit].replace("\n", "\n    "))
                w(f"    ... [truncated {len(text)-limit} chars]")

        resp = entry["response"].get("content") or {}
        resp_text = resp.get("text") or ""
        resp_mime = resp.get("mimeType") or ""
        if resp_text:
            w(f"  resp.body[{resp_mime}] ({len(resp_text)} chars):")
            limit = 2000
            if len(resp_text) <= limit:
                w("    " + resp_text.replace("\n", "\n    "))
            else:
                w("    " + resp_text[:limit].replace("\n", "\n    "))
                w(f"    ... [truncated {len(resp_text)-limit} chars]")

    pathlib.Path(out_path).write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {len(out)} lines to {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
