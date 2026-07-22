"""一次性抽 cardTypes / authorize 这两个关键 GraphQL batch 调用为 fixture。"""
import json
import pathlib
import sys
import re

har_path = pathlib.Path(sys.argv[1])
print(f"reading HAR: {har_path} ({har_path.stat().st_size / 1024 / 1024:.1f} MB)")
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
entries = data["log"]["entries"]
print(f"  entries: {len(entries)}")

# 查找 /graphql/（带尾斜杠是 hermes batch）请求里 cardTypes / authorize operation
results = {}
for i, e in enumerate(entries):
    url = e["request"]["url"]
    if not (url.endswith("/graphql/") or url.endswith("/graphql/?")):
        continue
    post = (e.get("request", {}).get("postData", {}) or {}).get("text", "") or ""
    op_match = re.search(r'"operationName":"([^"]+)"', post)
    if not op_match:
        continue
    op = op_match.group(1)
    if op not in ("cardTypes", "authorize"):
        continue
    if op in results:
        continue
    req = e["request"]
    res = e.get("response", {})
    fixture = {
        "har_source": str(har_path.name),
        "entry_index": i,
        "operation_name": op,
        "request": {
            "url": req["url"],
            "method": req["method"],
            "headers": [{"name": h["name"], "value": h["value"]} for h in req.get("headers", [])],
            "body_text": post,
            "body_json": json.loads(post) if post else None,
        },
        "response": {
            "status": res.get("status"),
            "headers": [{"name": h["name"], "value": h["value"]} for h in res.get("headers", [])],
            "body_text": (res.get("content", {}) or {}).get("text", ""),
        },
    }
    out = pathlib.Path(f"tests/fixtures/paypal_{op.lower()}_har.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> wrote {out} (entry [{i}], request_body={len(post)} chars, response_body={len(fixture['response']['body_text'])} chars)")
    results[op] = i
print(f"done; ops captured: {sorted(results.keys())}")
