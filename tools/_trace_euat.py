"""自动追踪 HAR 里 euat 的实际 value 是从哪里第一次出现的。"""
import json
import pathlib
import sys

har_path = pathlib.Path(sys.argv[1])
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
entries = data["log"]["entries"]
print(f"entries: {len(entries)}")

# Step 1: 找第一个带 x-paypal-internal-euat 请求 header 的 entry，抽出 value
euat_value = None
first_req_with_euat = -1
for i, e in enumerate(entries):
    for h in e.get("request", {}).get("headers", []):
        if h.get("name", "").lower() == "x-paypal-internal-euat":
            euat_value = h.get("value", "")
            first_req_with_euat = i
            break
    if euat_value:
        break

if not euat_value:
    print("no request has x-paypal-internal-euat header")
    sys.exit(0)

print(f"first request with euat: entry [{first_req_with_euat}]")
print(f"euat value: {euat_value[:80]}{'...' if len(euat_value)>80 else ''}")
print(f"euat length: {len(euat_value)} chars")

# Step 2: 在更早的 entry 里找这个 value 的来源
prefix = euat_value[:16]
print(f"\nsearching for prefix {prefix!r} in earlier responses ({first_req_with_euat} entries):")
print()

for i in range(first_req_with_euat):
    e = entries[i]
    url = e["request"]["url"]
    method = e["request"]["method"]
    status = e.get("response", {}).get("status", "?")
    res_body = ((e.get("response", {}).get("content", {}) or {}).get("text", "") or "")
    res_hdrs = e.get("response", {}).get("headers", [])

    in_body = prefix in res_body
    matching_hdrs = [h for h in res_hdrs if prefix in (h.get("value", "") or "")]

    if not (in_body or matching_hdrs):
        continue

    print(f"[{i}] {method} {url[:100]} -> {status}")
    if in_body:
        pos = res_body.find(prefix)
        snippet = res_body[max(0, pos - 80):pos + 200]
        print(f"   RES BODY pos={pos}: {snippet!r}")
    for h in matching_hdrs:
        print(f"   RES HDR {h['name']}: {h['value'][:150]}")
    print()
