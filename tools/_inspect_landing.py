"""一次性 HTML 分析脚本：找 PayPal 落地页里 _csrf / sessionID / ba_token 的真实位置。"""
import re
import sys
import pathlib

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools/captures/paypal_landing_1779552809.html")
h = path.read_text(encoding="utf-8", errors="replace")
print(f"file: {path}, length: {len(h)}\n")

for pat in ("sessionID", "_csrf", "x-csrf-token", "clientMetadataId", "PAYPAL-CLIENT-METADATA-ID", "euat", "x-paypal-internal-euat", "ba_token", "ec_token", "EC-", "BA-"):
    matches = list(re.finditer(pat, h))
    if not matches:
        print(f"== {pat!r}: NOT FOUND ==\n")
        continue
    print(f"== {pat!r}: {len(matches)} matches (first 3 contexts) ==")
    for m in matches[:3]:
        start = max(0, m.start() - 80)
        end = min(len(h), m.end() + 120)
        snippet = h[start:end].replace("\n", " ")
        print(f"  …{snippet}…")
    print()
