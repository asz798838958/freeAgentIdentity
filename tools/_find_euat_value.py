"""定位 HAR 里 euat 实际 value 的来源（哪个响应给的）。"""
import json
import pathlib
import sys

har_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools/captures/checkout-20260523-160436-04xg0pylps_edu.hsxhome.com.har")
target_prefix = sys.argv[2] if len(sys.argv) > 2 else "S23AAM"
data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))

for i, e in enumerate(data["log"]["entries"]):
    url = e["request"]["url"]

    # 检查请求 header（已知会带 euat）
    req_has = any(target_prefix in (h.get("value", "") or "") for h in e.get("request", {}).get("headers", []))

    # 检查响应 body
    res_body = ((e.get("response", {}).get("content", {}) or {}).get("text", "") or "")
    res_body_pos = res_body.find(target_prefix)

    # 检查响应 set-cookie / 其他 header
    res_hdr_matches = [(h["name"], h["value"][:120]) for h in e.get("response", {}).get("headers", []) if target_prefix in (h.get("value", "") or "")]

    if not (req_has or res_body_pos >= 0 or res_hdr_matches):
        continue

    print(f"[{i}] status={e.get('response',{}).get('status','?')} url={url[:100]}")
    if req_has:
        print(f"     -> REQUEST has euat token (header)")
    if res_body_pos >= 0:
        snippet = res_body[max(0, res_body_pos - 80):res_body_pos + 200]
        print(f"     -> RES BODY pos={res_body_pos}: {snippet!r}")
    for name, val in res_hdr_matches:
        print(f"     -> RES HDR {name}: {val}")
