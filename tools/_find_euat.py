"""定位 HAR 里 x-paypal-internal-euat token 第一次出现的位置和形态。"""
import json
import pathlib
import sys

har_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools/captures/checkout-20260523-160436-04xg0pylps_edu.hsxhome.com.har")
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))

print(f"entries: {len(data['log']['entries'])}")
first_with_euat = -1
for i, e in enumerate(data["log"]["entries"]):
    blob = json.dumps(e, ensure_ascii=False).lower()
    if "euat" not in blob:
        continue
    if first_with_euat < 0:
        first_with_euat = i

    in_req_url = "euat" in e["request"]["url"].lower()
    req_hdr_match = [h for h in e.get("request", {}).get("headers", []) if "euat" in (h.get("name", "") or "").lower() or "euat" in (h.get("value", "") or "").lower()]
    res_body = ((e.get("response", {}).get("content", {}) or {}).get("text", "") or "")
    res_body_pos = res_body.lower().find("euat") if res_body else -1
    res_hdr_match = [h for h in e.get("response", {}).get("headers", []) if "euat" in (h.get("value", "") or "").lower()]

    url = e["request"]["url"]
    print(f"[{i}] url={url[:100]}")
    print(f"     req_url_has_euat={in_req_url}, req_hdr_matches={len(req_hdr_match)}, res_body_pos={res_body_pos}, res_hdr_matches={len(res_hdr_match)}")
    if req_hdr_match:
        for h in req_hdr_match:
            print(f"     REQ HDR {h['name']}: {h['value'][:80]}")
    if res_body_pos >= 0:
        snippet = res_body[max(0, res_body_pos - 50):res_body_pos + 150]
        print(f"     RES BODY snippet: {snippet!r}")
    if res_hdr_match:
        for h in res_hdr_match:
            print(f"     RES HDR {h['name']}: {h['value'][:80]}")
    if i > first_with_euat + 5:
        break
