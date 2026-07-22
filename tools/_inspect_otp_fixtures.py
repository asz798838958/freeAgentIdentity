"""快速浏览 4 个 OTP fixture 的核心字段，用来反推 helper 的输入/输出形态。"""
import json
import pathlib

FILES = [
    "paypal_otp_challenge_har.json",
    "paypal_otp_initiate_har.json",
    "paypal_otp_confirm_har.json",
    "paypal_signup_retry_har.json",
]

base = pathlib.Path("tests/fixtures")
for fname in FILES:
    fpath = base / fname
    d = json.loads(fpath.read_text(encoding="utf-8"))
    print("=" * 80)
    print(f">>> {fname}")
    print(f"URL: {d['url']}")
    print(f"STATUS: {d['status']}")
    print(f"--- REQUEST BODY (first 1000):")
    print(d["request_body"][:1000])
    print()
    print(f"--- RESPONSE BODY (first 800):")
    print(d["response_body"][:800])
    print()
