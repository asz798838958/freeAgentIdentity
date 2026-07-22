"""列出 PayPal 协议链相关的所有 entry（graphql / hermes / checkoutweb / authorize / cardTypes）。"""
import json
import pathlib
import re
import sys

har_path = pathlib.Path(sys.argv[1])
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
entries = data["log"]["entries"]
start = int(sys.argv[2]) if len(sys.argv) > 2 else 0

for i, e in enumerate(entries):
    if i < start:
        continue
    url = e["request"]["url"]
    method = e["request"]["method"]
    status = e.get("response", {}).get("status", "?")
    if "/graphql" not in url and "/webapps/hermes" not in url and "/checkoutweb/" not in url:
        continue
    post = (e.get("request", {}).get("postData", {}) or {}).get("text", "") or ""
    ops = re.findall(r'"operationName":"([^"]+)"', post)
    ops_str = "/".join(ops) if ops else ""
    short = url[:80] + ("..." if len(url) > 80 else "")
    marker = []
    if "cardTypes" in post:
        marker.append("cardTypes")
    if '"operationName":"authorize"' in post or '"operationName": "authorize"' in post:
        marker.append("authorize")
    marker_str = " [" + ",".join(marker) + "]" if marker else ""
    print(f"[{i}] {method[:4]} {short} -> {status} ops={ops_str or '-'}{marker_str}")
