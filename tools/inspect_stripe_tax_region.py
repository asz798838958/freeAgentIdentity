"""HAR 实采 tax_region 提交响应里 invoice / elements_options.amount 是否更新（加税后）。"""
import json, sys
from pathlib import Path

har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not har_path:
    candidates = sorted(Path("tools/captures").glob("checkout-*.har"), reverse=True)
    if not candidates: print("missing har"); sys.exit(1)
    har_path = candidates[0]
print(f"HAR={har_path}\n")

har = json.loads(har_path.read_text(encoding="utf-8"))
entries = har["log"]["entries"]
for i, e in enumerate(entries):
    url = e["request"]["url"]
    method = e["request"]["method"]
    if "api.stripe.com/v1/payment_pages/" in url and method == "POST" \
       and not url.endswith("/init") and not url.endswith("/confirm") \
       and "/payment_pages/cs_" in url and "/" not in url.split("cs_", 1)[1].split("?", 1)[0].split("/", 1)[0] :
        # cs_id 后面没斜杠 → 这是 update_tax_region (POST /v1/payment_pages/{cs}) 不带后缀
        print(f"==== entry #{i} {method} {url} ====")
        post = (e["request"].get("postData") or {}).get("text") or ""
        print("REQ body:", post[:200])
        resp_text = (e["response"].get("content") or {}).get("text") or ""
        try:
            obj = json.loads(resp_text)
            interest_keys = ("amount", "amount_due", "amount_total", "total", "subtotal", "tax")
            def walk(o, path=""):
                if isinstance(o, dict):
                    for k, v in o.items():
                        p = f"{path}.{k}" if path else k
                        if k in interest_keys and not isinstance(v, (dict, list)):
                            print(f"  [resp] {p} = {v!r}")
                        walk(v, p)
                elif isinstance(o, list):
                    for idx, v in enumerate(o):
                        walk(v, f"{path}[{idx}]")
            walk(obj)
        except Exception as exc:
            print(f"  [resp parse error] {exc}")
        print()
