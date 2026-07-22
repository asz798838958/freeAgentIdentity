from __future__ import annotations

import json
import logging
from typing import Optional

from curl_cffi import requests

logger = logging.getLogger(__name__)
WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
WHAM_USAGE_USER_AGENT = "codex_cli_rs/0.76.0 (Debian 13.0.0; x86_64) WindowsTerminal"


def _proxies(proxy: Optional[str]) -> Optional[dict]:
    return {"http": proxy, "https": proxy} if proxy else None


def _account_id(account) -> str:
    extra = getattr(account, "extra", {}) or {}
    for value in (
        getattr(account, "chatgpt_account_id", ""),
        extra.get("chatgpt_account_id", ""),
        extra.get("chatgptAccountId", ""),
    ):
        if str(value or "").strip():
            return str(value).strip()
    id_token = getattr(account, "id_token", "") or extra.get("id_token", "")
    if isinstance(id_token, str) and id_token.strip().startswith("{"):
        try:
            id_token = json.loads(id_token)
        except Exception:
            id_token = None
    if isinstance(id_token, dict):
        for key in ("chatgpt_account_id", "chatgptAccountId", "account_id"):
            if str(id_token.get(key) or "").strip():
                return str(id_token[key]).strip()
    return ""


def _plan(value: str) -> str:
    raw = str(value or "").strip().lower()
    if any(token in raw for token in ("team", "enterprise", "business")):
        return "team"
    if any(token in raw for token in ("plus", "pro", "premium", "paid")):
        return "plus"
    return "free"


def _status_from_me(data: dict) -> str:
    status = _plan(data.get("plan_type"))
    if status != "free":
        return status
    for org in data.get("orgs", {}).get("data", []):
        status = _plan(org.get("settings", {}).get("workspace_plan_type"))
        if status != "free":
            return status
    return "free"


def _usage(account, proxy: Optional[str]) -> dict:
    headers = {"Authorization": f"Bearer {account.access_token}", "User-Agent": WHAM_USAGE_USER_AGENT}
    account_id = _account_id(account)
    if account_id:
        headers["Chatgpt-Account-Id"] = account_id
    response = requests.get(
        WHAM_USAGE_URL,
        headers=headers,
        proxies=_proxies(proxy),
        timeout=20,
        impersonate="chrome124",
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("wham/usage response format is invalid")
    return data


def fetch_subscription_status_details(account, proxy: Optional[str] = None) -> dict:
    if not account.access_token:
        raise ValueError("account access_token is empty")
    try:
        response = requests.get(
            "https://chatgpt.com/backend-api/me",
            headers={"Authorization": f"Bearer {account.access_token}", "Content-Type": "application/json"},
            proxies=_proxies(proxy),
            timeout=20,
            impersonate="chrome110",
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            usage = None
            try:
                usage = _usage(account, proxy)
            except Exception as exc:
                logger.info("usage enrichment failed: %s", exc)
            return {"status": _status_from_me(data), "source": "backend-api/me", "me": data, "usage": usage}
    except Exception as exc:
        logger.info("subscription status fallback to usage: %s", exc)
    usage = _usage(account, proxy)
    return {
        "status": _plan(usage.get("plan_type")),
        "source": "backend-api/wham/usage",
        "me": None,
        "usage": usage,
    }


def check_subscription_status(account, proxy: Optional[str] = None) -> str:
    return fetch_subscription_status_details(account, proxy=proxy)["status"]
