"""HAR 摘要脚本：按 host 与路径前缀聚合调用，挑出关键 API 端点供协议化反推使用。"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse


def main(har_path: str) -> None:
    data = json.loads(open(har_path, "rb").read())
    entries = data["log"]["entries"]

    by_host = Counter()
    by_host_method = defaultdict(Counter)
    interesting_hosts = (
        "chatgpt.com",
        "auth.openai.com",
        "pay.openai.com",
        "checkout.stripe.com",
        "api.stripe.com",
        "m.stripe.com",
        "merchant-ui-api.stripe.com",
        "www.paypal.com",
        "api.paypal.com",
        "openai.com",
    )
    interesting_endpoints: list[tuple[str, str, int, str]] = []

    for entry in entries:
        url = entry["request"]["url"]
        method = entry["request"]["method"]
        status = entry["response"]["status"]
        host = urlparse(url).hostname or "?"
        by_host[host] += 1
        by_host_method[host][method] += 1
        if any(host.endswith(target) for target in interesting_hosts):
            path = urlparse(url).path
            # 收掉静态资源（js/css/png 等）
            if path.endswith((".js", ".css", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ico", ".gif", ".mp4", ".webp")):
                continue
            interesting_endpoints.append((host, method, status, path))

    print("== HOSTS ==")
    for host, n in by_host.most_common(40):
        methods = ", ".join(f"{m}:{c}" for m, c in by_host_method[host].most_common())
        print(f"  {n:5d}  {host:<45s}  {methods}")

    print(f"\n== INTERESTING ENDPOINTS ({len(interesting_endpoints)}) ==")
    grouped: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    for host, method, status, path in interesting_endpoints:
        grouped[(host, method, path)] += 1
    for (host, method, path), n in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][2])):
        marker = "x" + str(n) if n > 1 else "  "
        print(f"  {marker:5s}  {method:6s} {host}{path}")


if __name__ == "__main__":
    main(sys.argv[1])
