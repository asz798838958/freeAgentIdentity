"""扫描 HAR 看 OTP_CHALLENGE 用的 csrfNonce / ctxId 来源是哪条前序响应。

`python tools\\inspect_har_otp_nonce.py [har_path] [target_entry]`

默认对最新一份 HAR 的 entry 505 (`/idapps/graphql` `getOtpChallengeOperation`)
的请求体抽 csrfNonce / ctxId，再扫前面所有 entries 的响应文本，定位它们最早出现
在哪一个响应里——便于决定协议模式从哪里拷贝这两个值。
"""

import json
import re
import sys
from pathlib import Path

har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "tools/captures/checkout-20260525-102401-ymz51oqk1h_edu.hsxhome.com.har"
)
target = int(sys.argv[2]) if len(sys.argv) > 2 else 505
har = json.loads(har_path.read_text(encoding="utf-8"))
entries = har["log"]["entries"]

body = (entries[target]["request"].get("postData") or {}).get("text") or ""
nonce_pat = '"csrfNonce":"'
ctx_pat = '"ctxId":"'
nonce = body.split(nonce_pat, 1)[1].split('"', 1)[0] if nonce_pat in body else ""
ctx = body.split(ctx_pat, 1)[1].split('"', 1)[0] if ctx_pat in body else ""
print(f"target entry {target}: nonce={nonce[:60]}... ctx={ctx[:60]}...")
print(f"nonce len={len(nonce)} ctx len={len(ctx)}")
print()


def _slot_in_text(needle: str, hay: str) -> bool:
    """需要把转义反斜杠版也算命中（PayPal 落地页里 csrfNonce 经常被当成
    React Server Component 字符串字面量序列化，反斜杠转义如 ``\\\"AAH...\\\"``）。"""
    if not needle:
        return False
    if needle in hay:
        return True
    # 30 个字符以内的前缀就够区分 PayPal 这类 base64-like token
    return needle[:30] in hay


for i in range(0, target):
    e = entries[i]
    text = e["response"].get("content", {}).get("text") or ""
    found_nonce = _slot_in_text(nonce, text)
    found_ctx = _slot_in_text(ctx, text)
    if found_nonce or found_ctx:
        url = e["request"]["url"]
        print(
            f"{i:4d} {e['request']['method']:5s} {url[:95]:<95s} "
            f"nonce={found_nonce} ctx={found_ctx}"
        )

# 顺便统计 entry461（落地页 HTML）里所有 csrf*/ctxId* 命中的窗口，便于人工核对。
landing_idx = 461 if target > 461 else max(0, target - 1)
landing_html = entries[landing_idx]["response"].get("content", {}).get("text") or ""
print()
print(f"---- entry {landing_idx} (landing HTML) keyword window ----")
print(f"size: {len(landing_html)} bytes")
for kw in ("csrfNonce", "otpCsrfNonce", "ctxId", "otpCtxId"):
    for m in re.finditer(re.escape(kw), landing_html):
        start = max(0, m.start() - 8)
        end = min(len(landing_html), m.end() + 110)
        print(f"  {kw} @ {m.start()}: {landing_html[start:end]!r}")
