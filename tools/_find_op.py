"""HAR 里查某个 GraphQL operationName 的所有请求详情。"""
import json
import pathlib
import sys

har_path = pathlib.Path(sys.argv[1])
op_name = sys.argv[2]
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
entries = data["log"]["entries"]

for i, e in enumerate(entries):
    post = e.get("request", {}).get("postData", {}) or {}
    body_text = post.get("text", "") or ""
    if f'"operationName":"{op_name}"' not in body_text and op_name not in e["request"]["url"]:
        continue
    req = e["request"]
    res = e.get("response", {})
    print(f"=== entry [{i}]: {op_name} ===")
    print(f"URL: {req['url']}")
    print(f"METHOD: {req['method']}")
    print(f"STATUS: {res.get('status', '?')}")
    print("REQUEST HEADERS:")
    for h in req.get("headers", []):
        val = h["value"]
        if len(val) > 220:
            val = val[:220] + "..."
        print(f"  {h['name']}: {val}")
    print()
