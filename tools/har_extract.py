"""按路径子串筛选 HAR 条目，打印请求方法/URL/headers/body 摘要，用于协议化反推。"""
from __future__ import annotations

import json
import sys
from urllib.parse import urlparse


def main(har_path: str, *patterns: str) -> None:
    out_path = None
    pat_list: list[str] = []
    for arg in patterns:
        if arg.startswith("--out="):
            out_path = arg[len("--out=") :]
        else:
            pat_list.append(arg)
    out_buf: list[str] = []

    def w(line: str = "") -> None:
        if out_path:
            out_buf.append(line)
        else:
            print(line)

    data = json.loads(open(har_path, "rb").read())
    entries = data["log"]["entries"]
    matched = 0
    for idx, entry in enumerate(entries):
        url = entry["request"]["url"]
        path = urlparse(url).path
        if not any(p in path for p in pat_list):
            continue
        matched += 1
        method = entry["request"]["method"]
        status = entry["response"]["status"]
        w("=" * 90)
        w(f"[{idx}] {method} {url}")
        w(f"  status: {status}")
        req_headers = {h["name"]: h["value"] for h in entry["request"]["headers"]}
        for key in ("Authorization", "Cookie", "Origin", "Referer", "Content-Type", "User-Agent",
                    "x-csrf-token", "x-paypal-internal-context", "x-paypal-client-metadata-id",
                    "paypal-client-context", "x-requested-with", "accept", "accept-language",
                    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest"):
            for k, v in req_headers.items():
                if k.lower() == key.lower():
                    if key.lower() == "cookie":
                        cookies = [c.strip().split("=")[0] for c in v.split(";") if c.strip()]
                        w(f"  req.{key}: ({len(cookies)} cookies) {', '.join(cookies[:8])}{'...' if len(cookies) > 8 else ''}")
                    elif len(v) > 200:
                        w(f"  req.{key}: {v[:200]}...({len(v)} chars)")
                    else:
                        w(f"  req.{key}: {v}")
        post = entry["request"].get("postData")
        if post:
            text = post.get("text") or ""
            mime = post.get("mimeType") or ""
            w(f"  req.body[{mime}] ({len(text)} chars):")
            if len(text) <= 2000:
                w("    " + text.replace("\n", "\n    "))
            else:
                w("    " + text[:2000].replace("\n", "\n    "))
                w(f"    ... [truncated {len(text)-2000} chars]")
        resp = entry["response"].get("content") or {}
        resp_text = resp.get("text") or ""
        resp_mime = resp.get("mimeType") or ""
        if resp_text:
            w(f"  resp.body[{resp_mime}] ({len(resp_text)} chars):")
            if len(resp_text) <= 1500:
                w("    " + resp_text.replace("\n", "\n    "))
            else:
                w("    " + resp_text[:1500].replace("\n", "\n    "))
                w(f"    ... [truncated {len(resp_text)-1500} chars]")
    w(f"\n[matched {matched} entries]")
    if out_path:
        import pathlib
        pathlib.Path(out_path).write_text("\n".join(out_buf), encoding="utf-8")
        print(f"wrote {len(out_buf)} lines to {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], *sys.argv[2:])
