"""完整 dump HAR entry 505 (OTP_CHALLENGE) 的所有 request headers。

之前的 inspect 脚本只 print 部分 header，可能漏了关键差异。
"""

import json
import sys
from pathlib import Path

har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "tools/captures/checkout-20260525-102401-ymz51oqk1h_edu.hsxhome.com.har"
)
har = json.loads(har_path.read_text(encoding="utf-8"))
entry = har["log"]["entries"][505]
print("URL:", entry["request"]["url"])
print("METHOD:", entry["request"]["method"])
print()
print("---- ALL request headers ----")
for h in entry["request"]["headers"]:
    val = h["value"]
    print(f"  {h['name']}: {val[:200]}{'...' if len(val) > 200 else ''}")
print()
print("---- response status / first 600 chars ----")
print("status:", entry["response"]["status"])
text = entry["response"]["content"].get("text", "") or ""
print(text[:600])
