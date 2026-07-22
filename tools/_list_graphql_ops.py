"""列出 HAR 里所有 /graphql 调用的 operationName 和 entry index。"""
import json
import pathlib
import sys
import re

har_path = pathlib.Path(sys.argv[1])
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
entries = data["log"]["entries"]

print(f"total entries: {len(entries)}")
print()
for i, e in enumerate(entries):
    url = e["request"]["url"]
    method = e["request"]["method"]
    status = e.get("response", {}).get("status", "?")
    if "/graphql" not in url:
        continue
    # 抽 operationName
    post = (e.get("request", {}).get("postData", {}) or {}).get("text", "") or ""
    ops = re.findall(r'"operationName":"([^"]+)"', post)
    ops_str = "/".join(ops) if ops else ""
    # url 里也可能有 ?OperationName
    url_op_match = re.search(r"\?([A-Za-z]+)$", url)
    url_op = url_op_match.group(1) if url_op_match else ""
    short_url = url[:80] + ("..." if len(url) > 80 else "")
    print(f"[{i}] {method} {short_url} -> {status} | url_op={url_op or '-'} | body_ops={ops_str or '-'}")
