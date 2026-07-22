"""从 HAR 实采里抽 Stripe ``/init`` 响应里的 payment_method_types 字段。

用于诊断 ``payment_method_types_mismatch`` 错误。关键查找:
- payment_method_types
- allowed_payment_method_types
- session.payment_method_types
- payment_method_options
"""

import json
import sys
from pathlib import Path

har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not har_path:
    candidates = sorted(Path("tools/captures").glob("checkout-*.har"), reverse=True)
    if not candidates:
        print("没找到 checkout-*.har"); sys.exit(1)
    har_path = candidates[0]
print(f"HAR={har_path}\n")

har = json.loads(har_path.read_text(encoding="utf-8"))
entries = har["log"]["entries"]

for i, e in enumerate(entries):
    url = e["request"]["url"]
    if "api.stripe.com/v1/payment_pages/" in url and url.endswith("/init"):
        print(f"==== /init entry #{i} URL: {url[:90]} ====")
        resp_text = (e["response"].get("content") or {}).get("text") or ""
        try:
            obj = json.loads(resp_text)
        except Exception as exc:
            print(f"无法解析响应 JSON: {exc}"); continue

        # 顶层关键 keys
        print("--- 顶层 keys ---")
        for k in sorted(obj.keys()):
            print(f"  {k}")

        # 寻找 payment_method_types 出现位置
        print("\n--- payment_method_types 出现位置 ---")
        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    p = f"{path}.{k}" if path else k
                    if "payment_method" in k.lower() and not isinstance(v, (dict,)):
                        print(f"  {p} = {v!r}")
                    elif "payment_method_type" in k.lower() and isinstance(v, list):
                        print(f"  {p} = {v!r}")
                    walk(v, p)
            elif isinstance(o, list):
                for idx, v in enumerate(o):
                    walk(v, f"{path}[{idx}]")
        walk(obj)
        break
