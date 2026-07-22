"""dump HAR 里某个 entry 的完整请求/响应详情。"""
import json
import pathlib
import sys

har_path = pathlib.Path(sys.argv[1])
idx = int(sys.argv[2])
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
e = data["log"]["entries"][idx]
req = e["request"]
res = e.get("response", {})

print(f"=== ENTRY {idx} ===")
print(f"URL: {req['url']}")
print(f"METHOD: {req['method']}")
print(f"STATUS: {res.get('status', '?')}")
print()
print("=== REQUEST HEADERS ===")
for h in req.get("headers", []):
    print(f"  {h['name']}: {h['value'][:200]}")
print()
post = req.get("postData", {})
if post and "text" in post:
    body = post["text"]
    if len(body) > 2000:
        print(f"=== REQUEST BODY ({len(body)} chars, first 1500) ===")
        print(body[:1500])
    else:
        print("=== REQUEST BODY ===")
        print(body)
print()
print("=== RESPONSE HEADERS ===")
for h in res.get("headers", []):
    print(f"  {h['name']}: {h['value'][:200]}")
print()
res_body = (res.get("content", {}) or {}).get("text", "") or ""
if res_body:
    if len(res_body) > 3000:
        print(f"=== RESPONSE BODY ({len(res_body)} chars, first 2500) ===")
        print(res_body[:2500])
    else:
        print("=== RESPONSE BODY ===")
        print(res_body)
