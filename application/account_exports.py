from __future__ import annotations

import base64
import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from core.datetime_utils import serialize_datetime
from domain.accounts import AccountExportSelection, AccountRecord
from infrastructure.accounts_repository import AccountsRepository


CHATGPT_PLATFORM = "chatgpt"
DEFAULT_CHATGPT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


@dataclass(slots=True)
class ExportArtifact:
    filename: str
    media_type: str
    content: str | bytes | io.BytesIO


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return {}


def _isoformat(value: datetime | None) -> str | None:
    return serialize_datetime(value)


def _timestamp_name(prefix: str, suffix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.{suffix}"


def _credential_value(item: AccountRecord, *keys: str) -> str:
    for key in keys:
        for credential in item.credentials or []:
            if credential.get("scope") == "platform" and credential.get("key") == key and credential.get("value"):
                return str(credential["value"])
    return ""


def _mailbox_provider_name(item: AccountRecord) -> str:
    for resource in item.provider_resources or []:
        if resource.get("resource_type") == "mailbox" and resource.get("provider_name"):
            return str(resource["provider_name"])
    for provider_account in item.provider_accounts or []:
        if provider_account.get("provider_type") == "mailbox" and provider_account.get("provider_name"):
            return str(provider_account["provider_name"])
    return ""


def _chatgpt_auth_info(*tokens: str) -> dict:
    merged: dict = {}
    for token in tokens:
        if not token:
            continue
        payload = _decode_jwt_payload(token)
        auth_info = payload.get("https://api.openai.com/auth", {})
        if isinstance(auth_info, dict):
            for key, value in auth_info.items():
                if value not in (None, "", [], {}):
                    merged[key] = value
    return merged


def _chatgpt_export_payload(item: AccountRecord) -> dict:
    access_token = _credential_value(item, "access_token", "accessToken", "legacy_token")
    refresh_token = _credential_value(item, "refresh_token", "refreshToken")
    id_token = _credential_value(item, "id_token", "idToken")
    session_token = _credential_value(item, "session_token", "sessionToken")
    workspace_id = _credential_value(item, "workspace_id", "workspaceId")
    payload = _decode_jwt_payload(access_token) if access_token else {}
    auth_info = _chatgpt_auth_info(access_token, id_token)
    client_id = _credential_value(item, "client_id", "clientId") or str(payload.get("client_id", "") or DEFAULT_CHATGPT_CLIENT_ID)
    cookies = _credential_value(item, "cookies", "cookie")
    account_id = item.user_id or _credential_value(item, "account_id", "chatgpt_account_id") or ""
    email_service = _mailbox_provider_name(item)

    if not account_id:
        account_id = str(auth_info.get("chatgpt_account_id", "") or auth_info.get("account_id", "") or "")
    if not workspace_id:
        workspace_id = str(auth_info.get("organization_id", "") or "")
    expires_at = None
    exp_timestamp = payload.get("exp")
    if isinstance(exp_timestamp, int) and exp_timestamp > 0:
        expires_at = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
    last_refresh_at = item.updated_at
    iat_timestamp = payload.get("iat")
    if isinstance(iat_timestamp, int) and iat_timestamp > 0:
        last_refresh_at = datetime.fromtimestamp(iat_timestamp, tz=timezone.utc)

    return {
        "id": item.id,
        "email": item.email,
        "password": item.password,
        "client_id": client_id,
        "account_id": account_id,
        "workspace_id": workspace_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "session_token": session_token,
        "cookies": cookies,
        "email_service": email_service,
        "registered_at": _isoformat(item.created_at),
        "last_refresh": _isoformat(last_refresh_at),
        "expires_at": _isoformat(expires_at),
        "status": item.display_status,
        "expires_at_unix": int(expires_at.timestamp()) if expires_at else 0,
    }


def _to_cpa_account(item: AccountRecord) -> SimpleNamespace:
    payload = _chatgpt_export_payload(item)
    return SimpleNamespace(
        email=payload["email"],
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        id_token=payload["id_token"],
        session_token=payload["session_token"],
        account_id=payload["account_id"],
        user_id=payload["account_id"],
        expired=payload["expires_at"],
        last_refresh=payload["last_refresh"],
        client_id=payload["client_id"],
        cookies=payload["cookies"],
        credentials={
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            "id_token": payload["id_token"],
            "session_token": payload["session_token"],
            "account_id": payload["account_id"],
            "chatgpt_account_id": payload["account_id"],
            "client_id": payload["client_id"],
            "cookies": payload["cookies"],
        },
    )


def _generate_cpa_token_json(item: AccountRecord) -> dict:
    from platforms.chatgpt.cpa_upload import generate_token_json

    return generate_token_json(_to_cpa_account(item))


def _make_sub2api_json(item: AccountRecord) -> dict:
    payload = _chatgpt_export_payload(item)
    return {
        "proxies": [],
        "accounts": [
            {
                "name": payload["email"],
                "platform": "openai",
                "type": "oauth",
                "credentials": {
                    "access_token": payload["access_token"],
                    "chatgpt_account_id": payload["account_id"],
                    "chatgpt_user_id": "",
                    "client_id": payload["client_id"],
                    "expires_at": payload["expires_at_unix"],
                    "expires_in": 863999,
                    "model_mapping": {
                        "gpt-5.1": "gpt-5.1",
                        "gpt-5.1-codex": "gpt-5.1-codex",
                        "gpt-5.1-codex-max": "gpt-5.1-codex-max",
                        "gpt-5.1-codex-mini": "gpt-5.1-codex-mini",
                        "gpt-5.2": "gpt-5.2",
                        "gpt-5.2-codex": "gpt-5.2-codex",
                    },
                    "organization_id": payload["workspace_id"],
                    "refresh_token": payload["refresh_token"],
                },
                "extra": {},
                "concurrency": 10,
                "priority": 1,
                "rate_multiplier": 1,
                "auto_pause_on_expired": True,
            }
        ],
    }


def _make_agent_identity_sub2api_json(item: AccountRecord) -> dict:
    payload = _chatgpt_export_payload(item)
    access_token = str(payload.get("access_token") or "").strip()
    id_token = str(payload.get("id_token") or "").strip()
    if not access_token:
        raise ValueError(
            f"账号 {item.email} 缺少 access_token，无法注册 Agent Identity"
        )

    identity_token = ""
    for candidate in (id_token, access_token):
        auth_info = _chatgpt_auth_info(candidate)
        if auth_info.get("chatgpt_account_id") and (
            auth_info.get("chatgpt_user_id")
            or auth_info.get("chatgpt_account_user_id")
            or auth_info.get("user_id")
        ):
            identity_token = candidate
            break
    if not identity_token:
        raise ValueError(
            f"账号 {item.email} 的 OAuth token 缺少 Agent Identity 所需账户 claims"
        )

    try:
        from platforms.chatgpt.from_credentials import (
            DEFAULT_AUTH_API_BASE_URL,
            DEFAULT_CODEX_BASE_URL,
            Error as AgentIdentityError,
            certificate_to_sub2api_export,
            register_identity,
        )
    except ImportError as exc:
        raise ValueError(
            "Agent Identity 导出依赖 PyNaCl，请先安装 requirements.txt"
        ) from exc

    try:
        certificate = register_identity(
            {"access_token": access_token, "id_token": identity_token},
            auth_api_base_url=DEFAULT_AUTH_API_BASE_URL,
            codex_base_url=DEFAULT_CODEX_BASE_URL,
        )
        return certificate_to_sub2api_export(certificate)
    except AgentIdentityError as exc:
        raise ValueError(f"账号 {item.email} 注册 Agent Identity 失败：{exc}") from exc


def _make_cockpit_token(item: AccountRecord) -> dict:
    payload = _chatgpt_export_payload(item)
    return {
        "type": "codex",
        "id_token": payload["id_token"],
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "account_id": payload["account_id"],
        "last_refresh": payload["last_refresh"] or "",
        "email": payload["email"],
        "expired": payload["expires_at"] or "",
        "account_note": "",
    }


def _make_kiro_go_account(item: AccountRecord) -> dict:
    """Convert a Kiro AccountRecord to Kiro-Go Account JSON format."""
    import uuid
    import time

    access_token = _credential_value(item, "accessToken", "access_token", "legacy_token")
    refresh_token = _credential_value(item, "refreshToken", "refresh_token")
    client_id = _credential_value(item, "clientId", "client_id")
    client_secret = _credential_value(item, "clientSecret", "client_secret")
    session_token = _credential_value(item, "sessionToken", "session_token")
    oauth_provider = _credential_value(item, "oauthProvider")

    # Determine auth method
    auth_method = "idc"
    provider = "BuilderId"
    if oauth_provider:
        lp = oauth_provider.lower()
        if lp in ("google", "github"):
            auth_method = "social"
            provider = "Google" if lp == "google" else "GitHub"

    return {
        "id": str(uuid.uuid4()),
        "email": item.email,
        "nickname": item.email.split("@")[0] if item.email else "",
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "clientId": client_id,
        "clientSecret": client_secret,
        "authMethod": auth_method,
        "provider": provider,
        "region": "us-east-1",
        "startUrl": "https://view.awsapps.com/start" if auth_method == "idc" else "",
        "expiresAt": int(time.time()) + 3600,
        "machineId": str(uuid.uuid4()),
        "weight": 0,
        "enabled": True,
    }


def _make_any2api_kiro_account(item: AccountRecord) -> dict:
    """Convert a Kiro AccountRecord to Any2API KiroAccount format."""
    import uuid

    access_token = _credential_value(item, "accessToken", "access_token", "legacy_token")
    return {
        "id": str(uuid.uuid4()),
        "name": item.email or f"Kiro Account",
        "accessToken": access_token,
        "machineId": str(uuid.uuid4()),
        "preferredEndpoint": "",
        "active": True,
        "updatedAt": _isoformat(item.updated_at) or _isoformat(item.created_at) or "",
    }


def _make_any2api_grok_token(item: AccountRecord) -> dict:
    """Convert a Grok AccountRecord to Any2API GrokToken format."""
    import uuid

    sso = _credential_value(item, "sso")
    sso_rw = _credential_value(item, "sso_rw")
    cookie_token = sso or sso_rw
    return {
        "id": str(uuid.uuid4()),
        "name": item.email or "Grok Token",
        "cookieToken": cookie_token,
        "active": True,
        "updatedAt": _isoformat(item.updated_at) or _isoformat(item.created_at) or "",
    }


def _build_any2api_admin_config(items: list[AccountRecord]) -> dict:
    """Build an Any2API admin.json from a list of accounts (multi-platform)."""
    kiro_accounts = []
    grok_tokens = []
    cursor_config = {}
    blink_config = {}
    chatgpt_config = {}

    for item in items:
        if item.platform == "kiro":
            kiro_accounts.append(_make_any2api_kiro_account(item))
        elif item.platform == "grok":
            grok_tokens.append(_make_any2api_grok_token(item))
        elif item.platform == "cursor":
            # Cursor uses a single cookie-based config, take the last one
            token = _credential_value(item, "session_token", "sessionToken", "wos_session", "legacy_token")
            if token:
                cursor_config = {"cookie": f"WorkosCursorSessionToken={token}"}
        elif item.platform == "blink":
            refresh = _credential_value(item, "firebase_refresh_token", "refresh_token", "refreshToken")
            id_token = _credential_value(item, "id_token", "idToken")
            session = _credential_value(item, "session_token", "sessionToken")
            slug = _credential_value(item, "workspace_slug", "workspaceSlug")
            if refresh or id_token:
                blink_config = {
                    "refreshToken": refresh,
                    "idToken": id_token,
                    "sessionToken": session,
                    "workspaceSlug": slug,
                }
        elif item.platform == "chatgpt":
            token = _credential_value(item, "access_token", "accessToken", "legacy_token")
            if token:
                chatgpt_config = {"token": token}

    providers = {}
    if kiro_accounts:
        providers["kiroAccounts"] = kiro_accounts
    if grok_tokens:
        providers["grokTokens"] = grok_tokens
    if cursor_config:
        providers["cursorConfig"] = cursor_config
    if blink_config:
        providers["blinkConfig"] = blink_config
    if chatgpt_config:
        providers["chatgptConfig"] = chatgpt_config

    return {
        "settings": {
            "adminPassword": "changeme",
            "apiKey": "0000",
            "defaultProvider": "kiro" if kiro_accounts else "cursor",
        },
        "providers": providers,
    }


class AccountExportsService:
    def __init__(self, repository: AccountsRepository | None = None):
        self.repository = repository or AccountsRepository()

    def export_chatgpt_json(self, selection: AccountExportSelection) -> ExportArtifact:
        items = self._load_chatgpt_items(selection)
        content = json.dumps(
            [
                {
                    "email": payload["email"],
                    "password": payload["password"],
                    "client_id": payload["client_id"],
                    "account_id": payload["account_id"],
                    "workspace_id": payload["workspace_id"],
                    "access_token": payload["access_token"],
                    "refresh_token": payload["refresh_token"],
                    "id_token": payload["id_token"],
                    "session_token": payload["session_token"],
                    "email_service": payload["email_service"],
                    "registered_at": payload["registered_at"],
                    "last_refresh": payload["last_refresh"],
                    "expires_at": payload["expires_at"],
                    "status": payload["status"],
                }
                for payload in [_chatgpt_export_payload(item) for item in items]
            ],
            ensure_ascii=False,
            indent=2,
        )
        return ExportArtifact(
            filename=_timestamp_name("accounts", "json"),
            media_type="application/json",
            content=content,
        )

    def export_chatgpt_csv(self, selection: AccountExportSelection) -> ExportArtifact:
        items = self._load_chatgpt_items(selection)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "Email",
                "Password",
                "Client ID",
                "Account ID",
                "Workspace ID",
                "Access Token",
                "Refresh Token",
                "ID Token",
                "Session Token",
                "Email Service",
                "Status",
                "Registered At",
                "Last Refresh",
                "Expires At",
            ]
        )
        for item in items:
            payload = _chatgpt_export_payload(item)
            writer.writerow(
                [
                    payload["id"],
                    payload["email"],
                    payload["password"],
                    payload["client_id"],
                    payload["account_id"],
                    payload["workspace_id"],
                    payload["access_token"],
                    payload["refresh_token"],
                    payload["id_token"],
                    payload["session_token"],
                    payload["email_service"],
                    payload["status"],
                    payload["registered_at"] or "",
                    payload["last_refresh"] or "",
                    payload["expires_at"] or "",
                ]
            )
        return ExportArtifact(
            filename=_timestamp_name("accounts", "csv"),
            media_type="text/csv",
            content=output.getvalue(),
        )

    def export_chatgpt_sub2api(self, selection: AccountExportSelection) -> ExportArtifact:
        items = self._load_chatgpt_items(selection)
        if len(items) == 1:
            item = items[0]
            content = json.dumps(_make_sub2api_json(item), ensure_ascii=False, indent=2)
            return ExportArtifact(
                filename=f"{item.email}_sub2api.json",
                media_type="application/json",
                content=content,
            )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                archive.writestr(
                    f"{item.email}_sub2api.json",
                    json.dumps(_make_sub2api_json(item), ensure_ascii=False, indent=2),
                )
        buffer.seek(0)
        return ExportArtifact(
            filename=_timestamp_name("sub2api_tokens", "zip"),
            media_type="application/zip",
            content=buffer,
        )

    def export_chatgpt_agent_identity_sub2api(
        self, selection: AccountExportSelection
    ) -> ExportArtifact:
        items = self._load_chatgpt_items(selection)
        if len(items) == 1:
            item = items[0]
            content = json.dumps(
                _make_agent_identity_sub2api_json(item),
                ensure_ascii=False,
                indent=2,
            )
            return ExportArtifact(
                filename=f"{item.email}_agent_identity_sub2api.json",
                media_type="application/json",
                content=content,
            )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                archive.writestr(
                    f"{item.email}_agent_identity_sub2api.json",
                    json.dumps(
                        _make_agent_identity_sub2api_json(item),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        buffer.seek(0)
        return ExportArtifact(
            filename=_timestamp_name("agent_identity_sub2api", "zip"),
            media_type="application/zip",
            content=buffer,
        )

    def export_chatgpt_cpa(self, selection: AccountExportSelection) -> ExportArtifact:
        items = self._load_chatgpt_items(selection)
        if len(items) == 1:
            item = items[0]
            content = json.dumps(_generate_cpa_token_json(item), ensure_ascii=False, indent=2)
            return ExportArtifact(
                filename=f"{item.email}.json",
                media_type="application/json",
                content=content,
            )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                archive.writestr(
                    f"{item.email}.json",
                    json.dumps(_generate_cpa_token_json(item), ensure_ascii=False, indent=2),
                )
        buffer.seek(0)
        return ExportArtifact(
            filename=_timestamp_name("cpa_tokens", "zip"),
            media_type="application/zip",
            content=buffer,
        )

    def _load_chatgpt_items(self, selection: AccountExportSelection) -> list[AccountRecord]:
        selection.platform = selection.platform or CHATGPT_PLATFORM
        if selection.platform != CHATGPT_PLATFORM:
            raise ValueError("仅支持 ChatGPT 账号导出")
        return self.repository.select_for_export(selection)

    def export_any2api(self, selection: AccountExportSelection) -> ExportArtifact:
        """导出账号为 Any2API admin.json 兼容格式。

        支持多平台：Kiro → kiroAccounts, Grok → grokTokens, Cursor/Blink/ChatGPT → 对应 config。
        """
        items = self.repository.select_for_export(selection)
        admin_config = _build_any2api_admin_config(items)
        content = json.dumps(admin_config, ensure_ascii=False, indent=2)
        return ExportArtifact(
            filename=_timestamp_name("any2api_admin", "json"),
            media_type="application/json",
            content=content,
        )
