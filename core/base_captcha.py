"""验证码解决器基类 — 具体实现已迁移到 providers/captcha/"""
from abc import ABC, abstractmethod


class BaseCaptcha(ABC):
    @abstractmethod
    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        """返回 Turnstile token"""
        ...

    @abstractmethod
    def solve_image(self, image_b64: str) -> str:
        """返回图片验证码文字"""
        ...

    def solve_recaptcha_v2(self, page_url: str, site_key: str) -> str:
        """返回 reCAPTCHA v2 token。"""
        raise NotImplementedError("当前验证码 provider 不支持 reCAPTCHA v2")

    def solve_hcaptcha(self, page_url: str, site_key: str) -> str:
        """返回 hCaptcha token。

        **PayPal 实战需要**：``paypal.com/pay/`` 风控页用的是 hCaptcha
        (siteKey 含在 ``paypalobjects.com/.../hcaptcha/hcaptcha_fph.html?siteKey=...``
        wrapper iframe URL 上)。``YesCaptcha`` / ``TwoCaptcha`` provider 都已经
        实现该方法；老 provider 如 ``ManualCaptcha`` / ``LocalSolverCaptcha``
        会落到这个默认实现并抛 ``NotImplementedError``——上层 ``payment.py`` 的
        ``_try_solve_detected_security_challenge`` 把它当普通错误处理（return
        False，进入手动等待 fallback）。
        """
        raise NotImplementedError("当前验证码 provider 不支持 hCaptcha")


# ---------------------------------------------------------------------------
# Lazy re-exports for backward compatibility
# (concrete classes now live under providers/captcha/)
# ---------------------------------------------------------------------------
_LAZY_IMPORTS = {
    "YesCaptcha": "providers.captcha.yescaptcha",
    "TwoCaptcha": "providers.captcha.twocaptcha",
    "ManualCaptcha": "providers.captcha.manual",
    "LocalSolverCaptcha": "providers.captcha.local_solver",
}


def __getattr__(name: str):
    module_path = _LAZY_IMPORTS.get(name)
    if module_path is not None:
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _definition_auth_fields(definition) -> list[str]:
    if not definition:
        return []
    return [
        str(field.get("key") or "")
        for field in definition.get_fields()
        if str(field.get("category") or "") == "auth" and str(field.get("key") or "")
    ]


def _normalize_captcha_provider_key(provider_key: str) -> str:
    aliases = {
        "yescaptcha": "yescaptcha_api",
        "2captcha": "twocaptcha_api",
        "twocaptcha": "twocaptcha_api",
    }
    key = str(provider_key or "").strip().lower()
    return aliases.get(key, key)


def has_captcha_configured(provider_key: str, extra: dict | None = None) -> bool:
    from infrastructure.provider_definitions_repository import ProviderDefinitionsRepository
    from infrastructure.provider_settings_repository import ProviderSettingsRepository

    key = _normalize_captcha_provider_key(provider_key)
    if key == "manual":
        return True

    definition = ProviderDefinitionsRepository().get_by_key("captcha", key)
    if not definition or not definition.enabled:
        return False

    merged = ProviderSettingsRepository().resolve_runtime_settings("captcha", key, extra or {})
    auth_fields = _definition_auth_fields(definition)
    if not auth_fields:
        return True
    return any(str(merged.get(field_key, "")).strip() for field_key in auth_fields)


def create_captcha_solver(provider_key: str, extra: dict | None = None) -> BaseCaptcha:
    from infrastructure.provider_definitions_repository import ProviderDefinitionsRepository
    from infrastructure.provider_settings_repository import ProviderSettingsRepository
    from providers.captcha.local_solver import LocalSolverCaptcha
    from providers.captcha.manual import ManualCaptcha
    from providers.captcha.twocaptcha import TwoCaptcha
    from providers.captcha.yescaptcha import YesCaptcha

    key = _normalize_captcha_provider_key(provider_key)
    if key == "manual":
        return ManualCaptcha()

    definition = ProviderDefinitionsRepository().get_by_key("captcha", key)
    if not definition or not definition.enabled:
        raise RuntimeError(f"验证码 provider 不存在或未启用: {key}")
    merged = ProviderSettingsRepository().resolve_runtime_settings("captcha", key, extra or {})
    driver_type = (definition.driver_type if definition else key).lower()

    if driver_type == "local_solver":
        return LocalSolverCaptcha(str(merged.get("solver_url", "") or ""))
    if driver_type == "yescaptcha_api":
        client_key = str(merged.get("yescaptcha_key", "") or "")
        if not client_key:
            raise RuntimeError("YesCaptcha Key 未配置，无法继续协议注册")
        return YesCaptcha(client_key)
    if driver_type == "twocaptcha_api":
        api_key = str(merged.get("twocaptcha_key", "") or "")
        if not api_key:
            raise RuntimeError("2Captcha Key 未配置，无法继续协议注册")
        return TwoCaptcha(api_key)
    raise ValueError(f"未知验证码解决器: {provider_key}")
