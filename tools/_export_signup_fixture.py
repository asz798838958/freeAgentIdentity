"""一次性把 SignUpNewMemberMutation 的 request/response 完整抽出来存为 fixture。

这样后续 helper 开发和单元测试都直接用 fixture，不用重复解析 97MB HAR。
"""
import json
import pathlib
import sys

har_path = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("tests/fixtures/paypal_signup_new_har.json")

print(f"reading HAR: {har_path} ({har_path.stat().st_size / 1024 / 1024:.1f} MB)")
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
entries = data["log"]["entries"]
print(f"  entries: {len(entries)}")

target = None
for i, e in enumerate(entries):
    url = e["request"]["url"]
    if "/graphql?SignUpNewMemberMutation" in url:
        target = (i, e)
        break
if not target:
    print("ERROR: SignUpNewMemberMutation not found")
    sys.exit(1)

idx, e = target
req = e["request"]
res = e.get("response", {})
post = req.get("postData", {}) or {}

# 解析 body
body_text = post.get("text", "") or ""
try:
    body_json = json.loads(body_text)
except Exception:
    body_json = None

# 整理为 fixture
fixture = {
    "har_source": str(har_path.name),
    "entry_index": idx,
    "request": {
        "url": req["url"],
        "method": req["method"],
        "headers": [{"name": h["name"], "value": h["value"]} for h in req.get("headers", [])],
        "body_text": body_text,
        "body_json": body_json,
    },
    "response": {
        "status": res.get("status"),
        "headers": [{"name": h["name"], "value": h["value"]} for h in res.get("headers", [])],
        "body_text": (res.get("content", {}) or {}).get("text", ""),
    },
}

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote fixture: {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
print(f"  request body length: {len(body_text)} chars")
print(f"  response body length: {len(fixture['response']['body_text'])} chars")
print(f"  request headers: {len(fixture['request']['headers'])}")
print(f"  response headers: {len(fixture['response']['headers'])}")
