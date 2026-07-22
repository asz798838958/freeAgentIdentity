"""对比 HAR 里 OTP_CHALLENGE / OTP_INITIATE / OTP_CONFIRM 的请求/响应 headers。

定位协议模式 OTP confirm 拿 ``PHONE_CONFIRMATION_NOT_INITIATED`` 的根因：
是某个浏览器里独有的 header / cookie 在我们协议模式漏发了，导致 PayPal 服务器
把 Initiate 与 Confirm 视为不同 fraud session。
"""

import json
import sys
from pathlib import Path

har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "tools/captures/checkout-20260525-102401-ymz51oqk1h_edu.hsxhome.com.har"
)
har = json.loads(har_path.read_text(encoding="utf-8"))
entries = har["log"]["entries"]


def fmt(value: str, width: int = 180) -> str:
    return value if len(value) <= width else value[:width] + "..."


def show_request(label: str, idx: int) -> None:
    e = entries[idx]
    print(f"========= {label} (entry {idx}) =========")
    print("URL:", e["request"]["url"])
    print("--- request headers ---")
    for h in e["request"]["headers"]:
        n = h["name"].lower()
        if (
            n.startswith("paypal-")
            or n.startswith("x-")
            or n in ("cookie", "referer", "origin", "content-type", "accept")
        ):
            print(f"  {h['name']}: {fmt(h['value'])}")
    print("--- response headers (Set-Cookie 与 paypal-* 相关) ---")
    for h in e["response"].get("headers", []):
        n = h["name"].lower()
        if n == "set-cookie" or n.startswith("paypal-") or n.startswith("x-"):
            print(f"  {h['name']}: {fmt(h['value'])}")
    print()


for label, idx in (
    ("OTP_CHALLENGE (idapps/graphql)", 505),
    ("OTP_INITIATE", 527),
    ("OTP_CONFIRM", 530),
    ("SIGNUP", 531),
):
    if idx < len(entries):
        show_request(label, idx)
