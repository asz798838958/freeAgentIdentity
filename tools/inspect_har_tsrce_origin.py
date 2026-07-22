"""扫 HAR：哪个响应 Set-Cookie 把 tsrce 设成 ``checkoutuinodeweb_weasley``。"""
import json
from pathlib import Path

har = json.loads(Path("tools/captures/checkout-20260525-102401-ymz51oqk1h_edu.hsxhome.com.har").read_text(encoding="utf-8"))
entries = har["log"]["entries"]
target_value = "checkoutuinodeweb_weasley"
print(f"target tsrce value: {target_value}\n")

for i, e in enumerate(entries):
    if i > 510:  # OTP_CHALLENGE 是 505，看到它即止
        break
    for h in e["response"].get("headers") or []:
        if h.get("name", "").lower() == "set-cookie":
            v = h.get("value", "")
            if v.startswith("tsrce=") and target_value in v:
                url = e["request"]["url"]
                print(f"#{i:4d} {e['request']['method']:5s} {url[:100]}")
                print(f"    Set-Cookie: {v[:200]}\n")
