"""HAR 实采 weasley logger 请求体 + 响应 Set-Cookie 完整内容。"""
import json
from pathlib import Path

har = json.loads(Path("tools/captures/checkout-20260525-102401-ymz51oqk1h_edu.hsxhome.com.har").read_text(encoding="utf-8"))
entries = har["log"]["entries"]
e = entries[479]
print(f"URL: {e['request']['url']}")
print(f"Method: {e['request']['method']}")
print(f"Status: {e['response']['status']}")
print(f"Content-Type response: {[h.get('value') for h in (e['response'].get('headers') or []) if h.get('name','').lower() == 'content-type']}")
print()
print("--- Request headers (filter) ---")
keep = {"content-type", "x-app-name", "x-requested-with", "accept", "origin", "referer", "cookie"}
for h in e["request"].get("headers") or []:
    n = h.get("name", "")
    if n.lower() in keep:
        v = h.get("value", "")
        print(f"  {n}: {v[:200]}")
print()
print("--- Request body (first 1500) ---")
body = (e["request"].get("postData") or {}).get("text") or ""
print(body[:1500])
print()
print("--- Response Set-Cookie (full list) ---")
for h in e["response"].get("headers") or []:
    if h.get("name", "").lower() == "set-cookie":
        print(f"  {h.get('value', '')[:240]}")
