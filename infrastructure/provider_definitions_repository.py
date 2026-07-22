from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from core.db import ProviderDefinitionModel, ProviderSettingModel, engine

logger = logging.getLogger(__name__)

SUPPORTED_MAILBOX_PROVIDER_KEYS = ("local_ms_pool", "api_mailbox")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_BUILTIN_DEFINITIONS: list[dict] = [
    # ── mailbox ──────────────────────────────────────────────────────
    {
        "provider_type": "mailbox",
        "provider_key": "local_ms_pool",
        "label": "本地微软邮箱池",
        "description": "导入 Hotmail/Outlook 邮箱池，支持 GuJumpgate 四列格式，优先使用 Client Id + 刷新令牌通过 Microsoft Graph 收验证码",
        "driver_type": "local_ms_pool",
        "default_auth_mode": "pool",
        "enabled": True,
        "category": "custom",
        "auth_modes": [{"value": "pool", "label": "账号池"}],
        "fields": [
            {
                "key": "local_ms_pool_file",
                "label": "账号池文件路径",
                "placeholder": "/Users/you/ms-mail-pool.txt",
                "category": "connection",
                "hint": "可选；每行一条 Hotmail 四列格式：账号----密码----ID----Token。也兼容旧通用格式。配置文件路径后无需把账号明文粘贴到设置页。",
            },
            {
                "key": "local_ms_pool_text",
                "label": "账号池文本",
                "type": "textarea",
                "category": "auth",
                "hint": "可选；直接粘贴 Hotmail 四列格式：账号----密码----ID----Token。也兼容旧通用格式。支持逗号、中文逗号、TAB、---- 分隔。",
            },
            {
                "key": "local_ms_graph_scope",
                "label": "Graph Scope",
                "placeholder": "https://graph.microsoft.com/Mail.Read offline_access",
                "category": "connection",
            },
            {
                "key": "local_ms_pool_state_file",
                "label": "占用状态文件",
                "placeholder": "默认 data/.local_ms_mailbox_pool_state.json",
                "category": "connection",
                "hint": "用于避免同一个邮箱被重复分配；清空该文件可重置账号池占用状态。",
            },
            {
                "key": "local_ms_pool_allow_reuse",
                "label": "允许重复使用邮箱",
                "type": "toggle",
                "category": "connection",
                "hint": "测试时可开启；批量注册建议关闭。",
            },
        ],
    },
    {
        "provider_type": "mailbox",
        "provider_key": "api_mailbox",
        "label": "API 邮箱",
        "description": "使用固定邮箱及其专属 API 地址轮询获取验证码，支持一行一个邮箱----API URL",
        "driver_type": "api_mailbox",
        "default_auth_mode": "pool",
        "enabled": True,
        "category": "custom",
        "auth_modes": [{"value": "pool", "label": "邮箱 API 池"}],
        "fields": [
            {
                "key": "api_mailbox_pool_text",
                "label": "邮箱 API 池",
                "type": "textarea",
                "secret": True,
                "category": "auth",
                "placeholder": "user@example.com----https://mail.example.com/api/code?email=...&token=...",
                "hint": "每行一组，格式：邮箱----完整 API URL。URL 中的邮箱、密码、Token 等参数请保持原样。",
            },
            {
                "key": "api_mailbox_poll_interval",
                "label": "轮询间隔秒",
                "placeholder": "3",
                "default_value": "3",
                "category": "connection",
            },
            {
                "key": "api_mailbox_request_timeout",
                "label": "单次请求超时秒",
                "placeholder": "15",
                "default_value": "15",
                "category": "connection",
            },
            {
                "key": "api_mailbox_state_file",
                "label": "占用状态文件",
                "placeholder": "默认 data/.api_mailbox_pool_state.json",
                "category": "connection",
                "hint": "用于避免同一个邮箱被重复分配；删除该文件可重置占用状态。",
            },
            {
                "key": "api_mailbox_allow_reuse",
                "label": "允许重复使用邮箱",
                "type": "toggle",
                "category": "connection",
                "hint": "测试时可开启；批量注册建议关闭。",
            },
        ],
    },
    {
        "provider_type": "captcha",
        "provider_key": "yescaptcha_api",
        "label": "YesCaptcha",
        "description": "YesCaptcha 云端验证码识别服务，支持 Turnstile 等类型",
        "driver_type": "yescaptcha_api",
        "default_auth_mode": "apikey",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "apikey", "label": "API Key"}],
        "fields": [
            {"key": "yescaptcha_key", "label": "Client Key", "secret": True},
        ],
    },
    {
        "provider_type": "captcha",
        "provider_key": "twocaptcha_api",
        "label": "2Captcha",
        "description": "2Captcha 云端验证码识别服务，支持 Turnstile 等类型",
        "driver_type": "twocaptcha_api",
        "default_auth_mode": "apikey",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [{"value": "apikey", "label": "API Key"}],
        "fields": [
            {"key": "twocaptcha_key", "label": "API Key", "secret": True},
        ],
    },
    {
        "provider_type": "captcha",
        "provider_key": "local_solver",
        "label": "本地验证码求解器",
        "description": "调用本地 api_solver 服务（Camoufox/patchright）解 Turnstile 验证码",
        "driver_type": "local_solver",
        "default_auth_mode": "",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [
            {"key": "solver_url", "label": "Solver 地址", "placeholder": "http://localhost:8889"},
        ],
    },
    {
        "provider_type": "captcha",
        "provider_key": "manual",
        "label": "人工打码",
        "description": "阻塞等待用户手动输入验证码，适用于调试场景",
        "driver_type": "manual",
        "default_auth_mode": "",
        "enabled": True,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [],
    },
    # ── proxy ────────────────────────────────────────────────────────
    {
        "provider_type": "proxy",
        "provider_key": "api_extract",
        "label": "API 提取代理",
        "description": "通过 HTTP API 动态提取代理 IP 列表，适用于大多数代理商的 API 提取接口",
        "driver_type": "api_extract",
        "default_auth_mode": "",
        "enabled": False,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [
            {"key": "proxy_api_url", "label": "API 地址", "placeholder": "https://provider.com/api/get_proxy?key=xxx"},
            {"key": "proxy_protocol", "label": "协议", "placeholder": "http / socks5"},
            {"key": "proxy_username", "label": "用户名 (可选)"},
            {"key": "proxy_password", "label": "密码 (可选)", "secret": True},
        ],
    },
    {
        "provider_type": "proxy",
        "provider_key": "rotating_gateway",
        "label": "旋转网关代理",
        "description": "固定入口地址，每次请求自动分配不同出口 IP，适用于 BrightData / Oxylabs / IPRoyal 等",
        "driver_type": "rotating_gateway",
        "default_auth_mode": "",
        "enabled": False,
        "category": "thirdparty",
        "auth_modes": [],
        "fields": [
            {"key": "proxy_gateway_url", "label": "网关地址", "placeholder": "http://user:pass@gate.example.com:7777"},
        ],
    },
]


class ProviderDefinitionsRepository:

    def ensure_seeded(self) -> None:
        """将内置 provider definition 种子数据写入数据库。

        新增的插入，已存在的更新字段定义（label、description、fields 等），
        确保代码升级后内置 provider 的元数据能同步到数据库。
        """
        with Session(engine) as session:
            existing: dict[str, ProviderDefinitionModel] = {}
            for row in session.exec(select(ProviderDefinitionModel)).all():
                key = f"{row.provider_type}::{row.provider_key}"
                existing[key] = row

            changed = False
            for seed in _BUILTIN_DEFINITIONS:
                key = f"{seed['provider_type']}::{seed['provider_key']}"
                item = existing.get(key)

                if item is None:
                    # 新增
                    item = ProviderDefinitionModel(
                        provider_type=seed["provider_type"],
                        provider_key=seed["provider_key"],
                        created_at=_utcnow(),
                    )
                    logger.info("种子数据: 新增 %s/%s", seed["provider_type"], seed["provider_key"])

                # 更新元数据（每次启动都同步，确保代码变更生效）
                item.label = seed.get("label", seed["provider_key"])
                item.description = seed.get("description", "")
                item.driver_type = seed.get("driver_type", seed["provider_key"])
                item.default_auth_mode = seed.get("default_auth_mode", "")
                item.enabled = (
                    seed["provider_key"] in SUPPORTED_MAILBOX_PROVIDER_KEYS
                    if seed["provider_type"] == "mailbox"
                    else seed.get("enabled", True)
                )
                item.is_builtin = True
                item.category = seed.get("category", "")
                item.set_auth_modes(list(seed.get("auth_modes") or []))
                item.set_fields(list(seed.get("fields") or []))
                if not item.get_metadata():
                    # 只在 metadata 为空时写入种子值，避免覆盖用户自定义的 pipeline
                    item.set_metadata(dict(seed.get("metadata") or {}))
                item.updated_at = _utcnow()
                session.add(item)
                changed = True

            # Keep historical/custom mailbox definitions in the database so
            # upgrades are non-destructive, but remove them from active use.
            for item in existing.values():
                if (
                    item.provider_type == "mailbox"
                    and item.provider_key not in SUPPORTED_MAILBOX_PROVIDER_KEYS
                    and item.enabled
                ):
                    item.enabled = False
                    item.updated_at = _utcnow()
                    session.add(item)
                    changed = True

            if changed:
                session.commit()

    # ── 查询（全部从 DB） ────────────────────────────────────────────

    def list_by_type(self, provider_type: str, *, enabled_only: bool = False) -> list[ProviderDefinitionModel]:
        with Session(engine) as session:
            query = select(ProviderDefinitionModel).where(ProviderDefinitionModel.provider_type == provider_type)
            if enabled_only:
                query = query.where(ProviderDefinitionModel.enabled == True)  # noqa: E712
            items = session.exec(query.order_by(ProviderDefinitionModel.id)).all()
            if provider_type == "mailbox":
                items = [item for item in items if item.provider_key in SUPPORTED_MAILBOX_PROVIDER_KEYS]
            return items

    def get_by_key(self, provider_type: str, provider_key: str) -> ProviderDefinitionModel | None:
        with Session(engine) as session:
            return session.exec(
                select(ProviderDefinitionModel)
                .where(ProviderDefinitionModel.provider_type == provider_type)
                .where(ProviderDefinitionModel.provider_key == provider_key)
            ).first()

    def list_driver_templates(self, provider_type: str) -> list[dict]:
        """从 DB 读取：按 driver_type 去重，返回可用驱动模板列表。"""
        with Session(engine) as session:
            definitions = session.exec(
                select(ProviderDefinitionModel)
                .where(ProviderDefinitionModel.provider_type == provider_type)
                .order_by(ProviderDefinitionModel.is_builtin.desc(), ProviderDefinitionModel.id)
            ).all()
        seen: dict[str, dict] = {}
        for d in definitions:
            if provider_type == "mailbox" and d.provider_key not in SUPPORTED_MAILBOX_PROVIDER_KEYS:
                continue
            dt = d.driver_type or ""
            if dt and dt not in seen:
                seen[dt] = {
                    "provider_type": d.provider_type,
                    "provider_key": d.provider_key,
                    "driver_type": dt,
                    "label": d.label,
                    "description": d.description,
                    "default_auth_mode": d.default_auth_mode,
                    "auth_modes": d.get_auth_modes(),
                    "fields": d.get_fields(),
                }
        return list(seen.values())

    def _get_driver_defaults(self, provider_type: str, driver_type: str) -> dict | None:
        """从 DB 中查找同 driver_type 的已有 definition 作为模板。"""
        with Session(engine) as session:
            ref = session.exec(
                select(ProviderDefinitionModel)
                .where(ProviderDefinitionModel.provider_type == provider_type)
                .where(ProviderDefinitionModel.driver_type == driver_type)
                .order_by(ProviderDefinitionModel.is_builtin.desc(), ProviderDefinitionModel.id)
            ).first()
            if not ref:
                return None
            return {
                "default_auth_mode": ref.default_auth_mode,
                "auth_modes": ref.get_auth_modes(),
                "fields": ref.get_fields(),
            }

    # ── 写入 ────────────────────────────────────────────────────────

    def save(
        self,
        *,
        definition_id: int | None,
        provider_type: str,
        provider_key: str,
        label: str,
        description: str,
        driver_type: str,
        enabled: bool,
        default_auth_mode: str = "",
        metadata: dict | None = None,
    ) -> ProviderDefinitionModel:
        defaults = self._get_driver_defaults(provider_type, driver_type)

        with Session(engine) as session:
            if definition_id:
                item = session.get(ProviderDefinitionModel, definition_id)
                if not item:
                    raise ValueError("provider definition 不存在")
            else:
                item = session.exec(
                    select(ProviderDefinitionModel)
                    .where(ProviderDefinitionModel.provider_type == provider_type)
                    .where(ProviderDefinitionModel.provider_key == provider_key)
                ).first()
                if not item:
                    item = ProviderDefinitionModel(
                        provider_type=provider_type,
                        provider_key=provider_key,
                    )
                    item.created_at = _utcnow()

            item.provider_type = provider_type
            item.provider_key = provider_key
            item.label = label or provider_key
            item.description = description or ""
            item.driver_type = driver_type
            item.default_auth_mode = default_auth_mode or item.default_auth_mode or (defaults.get("default_auth_mode", "") if defaults else "")
            item.enabled = bool(enabled)
            if not item.get_auth_modes() and defaults:
                item.set_auth_modes(list(defaults.get("auth_modes") or []))
            if not item.get_fields() and defaults:
                item.set_fields(list(defaults.get("fields") or []))
            item.set_metadata(dict(metadata or {}))
            item.updated_at = _utcnow()
            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def delete(self, definition_id: int) -> bool:
        with Session(engine) as session:
            item = session.get(ProviderDefinitionModel, definition_id)
            if not item:
                return False
            has_settings = session.exec(
                select(ProviderSettingModel)
                .where(ProviderSettingModel.provider_type == item.provider_type)
                .where(ProviderSettingModel.provider_key == item.provider_key)
            ).first()
            if has_settings:
                raise ValueError("请先删除对应 provider 配置，再删除 definition")
            session.delete(item)
            session.commit()
            return True
