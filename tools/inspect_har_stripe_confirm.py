"""从 HAR 实采里抽 Stripe ``/confirm`` 请求的完整 body 字段，定位 ``expected_amount``。"""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl

har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not har_path:
    candidates = sorted(Path("tools/captures").glob("checkout-*.har"), reverse=True)
    if not candidates:
        print("没找到 checkout-*.har，请显式给路径", file=sys.stderr); sys.exit(1)
    har_path = candidates[0]
print(f"HAR={har_path}")

har = json.loads(har_path.read_text(encoding="utf-8"))
entries = har["log"]["entries"]

# Stripe init 也看下，作为 expected_amount 来源候选
for kind, needle in [("init", "/init"), ("confirm", "/confirm")]:
    print(f"\n========= Stripe {kind} (POST {needle}) =========")
    for i, e in enumerate(entries):
        url = e["request"]["url"]
        if "api.stripe.com/v1/payment_pages/" in url and url.endswith(needle):
            print(f"entry #{i} URL: {url}")
            post = (e["request"].get("postData") or {}).get("text") or ""
            params = dict(parse_qsl(post, keep_blank_values=True))
            for k, v in sorted(params.items()):
                short = v if len(v) < 120 else (v[:117] + "...")
                print(f"  {k}: {short}")
            # init 响应里看 amount
            if kind == "init":
                resp_text = (e["response"].get("content") or {}).get("text") or ""
                try:
                    obj = json.loads(resp_text)
                    # 看 amount / total / payment_intent / subscription 字段
                    interest_keys = (
                        "amount", "amount_due", "amount_total", "expected_amount",
                        "currency", "total", "subtotal",
                    )
                    def walk(o, path=""):
                        if isinstance(o, dict):
                            for k, v in o.items():
                                p = f"{path}.{k}"
                                if k in interest_keys and not isinstance(v, (dict, list)):
                                    print(f"    [resp] {p} = {v!r}")
                                walk(v, p)
                        elif isinstance(o, list):
                            for i2, v in enumerate(o):
                                walk(v, f"{path}[{i2}]")
                    walk(obj)
                except Exception as exc:
                    print(f"    [resp parse error] {exc}")
            break
    else:
        print(f"  (没找到 {needle} entry)")
