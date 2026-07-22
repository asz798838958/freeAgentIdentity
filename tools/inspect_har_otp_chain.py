"""临时脚本：列出 HAR 里 OTP 周边（[460, 540)）的 graphql/auth/idapps 请求顺序。

用于对比 Camoufox 浏览器流程的真实请求链与协议模式实现，定位漏请求/顺序差异。
"""

import json
import re
import sys
from pathlib import Path

har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "tools/captures/checkout-20260525-102401-ymz51oqk1h_edu.hsxhome.com.har"
)
har = json.loads(har_path.read_text(encoding="utf-8"))
entries = har["log"]["entries"]

op_pat = re.compile(r'"operationName"\s*:\s*"([^"]+)"')

start = int(sys.argv[2]) if len(sys.argv) > 2 else 460
end = int(sys.argv[3]) if len(sys.argv) > 3 else 540
hot = ("/auth/", "/graphql", "/idapps", "/logger/", "tealeaf", "signup")

for i in range(start, min(end, len(entries))):
    e = entries[i]
    url = e["request"]["url"]
    if not any(s in url for s in hot):
        continue
    body = (e["request"].get("postData") or {}).get("text") or ""
    m = op_pat.search(body[:400])
    op = m.group(1) if m else ""
    status = e["response"].get("status")
    print(f"{i:4d} {e['request']['method']:5s} {status:>3} {url[:95]:<95s} op={op}")
