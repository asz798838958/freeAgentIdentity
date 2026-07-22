from __future__ import annotations

from typing import Any

from sqlmodel import Session

from core.account_graph import load_account_graphs, sync_account_graph
from core.base_platform import Account as PlatformAccount
from core.base_platform import AccountStatus
from core.db import AccountModel


PLATFORM_TOKEN_KEY_PRIORITY: dict[str, list[str]] = {
    "cursor": ["session_token", "sessionToken", "legacy_token"],
    "chatgpt": ["access_token", "accessToken", "legacy_token", "session_token", "sessionToken"],
    "kiro": ["accessToken", "access_token", "legacy_token", "sessionToken", "session_token"],
    "trae": ["legacy_token", "access_token", "accessToken"],
    "blink": ["firebase_refresh_token", "legacy_token", "refresh_token", "access_token", "session_token"],
    "windsurf": ["session_token", "sessionToken", "legacy_token", "auth_token", "authToken"],
}


def _load_graph(session: Session, model: AccountModel) -> dict[str, Any]:
    account_id = int(model.id or 0)
    graphs = load_account_graphs(session, [account_id]) if account_id else {}
    graph = graphs.get(account_id)
    if graph is None and account_id:
        sync_account_graph(session, model)
        session.commit()
        graph = load_account_graphs(session, [account_id]).get(account_id, {})
    return graph or {}


def _platform_credentials(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in list(graph.get("credentials") or [])
        if isinstance(item, dict) and item.get("scope") == "platform"
    ]


def _credential_value(graph: dict[str, Any], *keys: str) -> str:
    credentials = _platform_credentials(graph)
    for key in keys:
        for item in credentials:
            if item.get("key") == key and item.get("value") not in (None, ""):
                return str(item["value"])
    return ""


def resolve_primary_token(model: AccountModel, graph: dict[str, Any] | None = None) -> str:
    graph = graph or {}
    priority = PLATFORM_TOKEN_KEY_PRIORITY.get(
        model.platform,
        ["access_token", "accessToken", "session_token", "sessionToken", "legacy_token"],
    )
    token = _credential_value(graph, *priority)
    if token:
        return token
    for item in _platform_credentials(graph):
        if item.get("credential_type") == "token" and item.get("value") not in (None, ""):
            return str(item["value"])
    return ""


def _overview_value(graph: dict[str, Any], key: str, default: Any = "") -> Any:
    overview = graph.get("overview")
    if isinstance(overview, dict) and key in overview:
        return overview.get(key)
    return default


def build_platform_extra(model: AccountModel, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = graph or {}
    extra: dict[str, Any] = {}
    overview = graph.get("overview")
    if isinstance(overview, dict) and overview:
        extra["account_overview"] = overview
        for key in ("cashier_url", "region", "trial_end_time"):
            if overview.get(key) not in (None, ""):
                extra[key] = overview.get(key)
    provider_accounts = list(graph.get("provider_accounts") or [])
    if provider_accounts:
        extra["provider_accounts"] = provider_accounts
    provider_resources = list(graph.get("provider_resources") or [])
    if provider_resources:
        extra["provider_resources"] = provider_resources
    for item in _platform_credentials(graph):
        key = str(item.get("key") or "")
        value = item.get("value")
        if key and value not in (None, ""):
            extra[key] = value
    return extra


def build_platform_account(session: Session, model: AccountModel) -> PlatformAccount:
    graph = _load_graph(session, model)
    try:
        status = AccountStatus(_overview_value(graph, "lifecycle_status", AccountStatus.REGISTERED.value) or AccountStatus.REGISTERED.value)
    except ValueError:
        status = AccountStatus.REGISTERED
    return PlatformAccount(
        platform=model.platform,
        email=model.email,
        password=model.password,
        user_id=model.user_id,
        region=str(_overview_value(graph, "region", "") or ""),
        token=resolve_primary_token(model, graph),
        status=status,
        trial_end_time=int(_overview_value(graph, "trial_end_time", 0) or 0),
        extra=build_platform_extra(model, graph),
    )
