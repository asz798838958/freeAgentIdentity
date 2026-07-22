"""一次性把 HAR 里 OTP 子链相关的 4 个调用抽成 fixture，用于离线 1:1 对比。

抽取目标：
- entry 533: POST /idapps/graphql {operationName: getOtpChallengeOperation}
- entry 534: POST /graphql?InitiateRiskBasedTwoFactorPhoneConfirmationMutation
- entry 540: POST /graphql?ConfirmRiskBasedTwoFactorPhoneConfirmationMutation
- entry 541: POST /graphql?SignUpNewMemberMutation (重发，带 accessToken)
"""
import json
import pathlib
import sys

HAR_PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                        else "tools/captures/checkout-20260523-231343-j8miwlvsz3_edu.hsxhome.com.har")
OUT_DIR = pathlib.Path("tests/fixtures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

data = json.loads(HAR_PATH.read_text(encoding="utf-8", errors="replace"))
entries = data["log"]["entries"]

# (entry_index, fixture_name)
TARGETS = [
    (533, "paypal_otp_challenge_har.json"),
    (534, "paypal_otp_initiate_har.json"),
    (540, "paypal_otp_confirm_har.json"),
    (541, "paypal_signup_retry_har.json"),
]

for idx, fname in TARGETS:
    e = entries[idx]
    req = e["request"]
    res = e.get("response", {})
    fixture = {
        "entry_index": idx,
        "url": req["url"],
        "method": req["method"],
        "status": res.get("status"),
        "request_headers": {h["name"]: h["value"] for h in req.get("headers", [])},
        "request_body": (req.get("postData", {}) or {}).get("text", ""),
        "response_headers": {h["name"]: h["value"] for h in res.get("headers", [])},
        "response_body": (res.get("content", {}) or {}).get("text", ""),
    }
    out = OUT_DIR / fname
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{idx}] -> {out} ({len(fixture['request_body'])} req + {len(fixture['response_body'])} resp)")

print("done.")
