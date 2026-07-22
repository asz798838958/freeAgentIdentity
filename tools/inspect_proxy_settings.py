"""检查当前数据库里启用的代理 provider 配置。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from infrastructure.provider_settings_repository import ProviderSettingsRepository

repo = ProviderSettingsRepository()
all_settings = repo.list_by_type("proxy")
print(f"==== 所有 proxy provider settings (总 {len(all_settings)}) ====")
for s in all_settings:
    print(f"  enabled={s.enabled} provider_key={s.provider_key}")
    cfg = s.get_config()
    for k, v in cfg.items():
        vstr = str(v)
        # 掩码长 URL
        if len(vstr) > 70:
            vstr = vstr[:70] + "..."
        # 掩码 user:pass
        import re as _re
        vstr = _re.sub(r"(://)([^:]+):([^@]+)@", r"\1***:***@", vstr)
        print(f"    cfg[{k}] = {vstr}")

print()
print("==== 静态 ProxyModel 数据库 ====")
from sqlmodel import Session, select
from core.db import ProxyModel, engine
with Session(engine) as s:
    proxies = s.exec(select(ProxyModel)).all()
    print(f"total: {len(proxies)}")
    for p in proxies[:10]:
        url = p.url or ""
        import re as _re
        url_masked = _re.sub(r"(://)([^:]+):([^@]+)@", r"\1***:***@", url)
        print(f"  is_active={p.is_active} region={p.region!r} url={url_masked} success={p.success_count} fail={p.fail_count}")
