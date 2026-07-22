from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from application.provider_settings import ProviderSettingsService

router = APIRouter(prefix="/provider-settings", tags=["provider-settings"])
service = ProviderSettingsService()


class ProviderSettingUpsertRequest(BaseModel):
    id: int | None = None
    provider_type: str
    provider_key: str
    display_name: str = ""
    auth_mode: str = ""
    enabled: bool = True
    is_default: bool = False
    config: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, str] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


@router.get("")
def list_provider_settings(provider_type: str):
    return service.list_settings(provider_type)


@router.put("")
def save_provider_setting(body: ProviderSettingUpsertRequest):
    try:
        return service.save_setting(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("")
def create_provider_setting(body: ProviderSettingUpsertRequest):
    try:
        return service.save_setting(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/{setting_id}")
def delete_provider_setting(setting_id: int):
    result = service.delete_setting(setting_id)
    if not result["ok"]:
        raise HTTPException(404, "provider setting 不存在")
    return result


class ProviderTestRequest(BaseModel):
    provider_type: str
    provider_key: str
    config: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, str] = Field(default_factory=dict)


@router.post("/test")
def test_provider(body: ProviderTestRequest):
    """测试 provider 配置是否正确 — 尝试创建/获取一个邮箱地址。"""
    from infrastructure.provider_definitions_repository import ProviderDefinitionsRepository

    definitions = ProviderDefinitionsRepository()
    definition = definitions.get_by_key(body.provider_type, body.provider_key)
    if not definition:
        return {"ok": False, "error": f"未找到 provider 定义: {body.provider_key}"}

    # Merge config + auth into a flat dict (same as runtime)
    extra = {**body.config, **body.auth}

    if body.provider_type == "mailbox":
        return _test_mailbox(definition.driver_type or body.provider_key, extra, definition)
    elif body.provider_type == "captcha":
        return {"ok": True, "message": "验证码服务暂不支持在线测试，请在注册任务中验证"}
    return {"ok": False, "error": f"不支持测试的 provider 类型: {body.provider_type}"}


def _test_mailbox(driver_type: str, extra: dict, definition) -> dict:
    """尝试用给定配置创建一个邮箱，验证配置是否正确。"""
    import traceback
    from core.base_mailbox import MAILBOX_FACTORY_REGISTRY

    factory = MAILBOX_FACTORY_REGISTRY.get(driver_type)
    if not factory:
        return {"ok": False, "error": f"未找到邮箱驱动: {driver_type}"}

    try:
        mailbox = factory(extra, None)

        if hasattr(mailbox, "peek_email"):
            email = mailbox.peek_email()
            return {
                "ok": True,
                "message": f"测试成功！可用邮箱: {email}",
                "email": email,
            }

        account = mailbox.get_email()
        return {
            "ok": True,
            "message": f"测试成功！生成邮箱: {account.email}",
            "email": account.email,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"测试失败: {str(exc)}",
            "detail": traceback.format_exc()[-500:],
        }
