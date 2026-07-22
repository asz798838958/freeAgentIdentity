"""Account CRUD endpoint tests."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from application.account_exports import AccountExportsService
from core.base_platform import Account
from core.db import save_account
from domain.accounts import AccountExportSelection, AccountQuery
from infrastructure.accounts_repository import AccountsRepository


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


def _create_account(**overrides):
    payload = {
        "platform": "chatgpt",
        "email": "test@example.com",
        "password": "TestPass123!",
        **overrides,
    }
    save_account(Account(**payload))
    _, records = AccountsRepository().list(
        AccountQuery(platform=payload["platform"], email=payload["email"])
    )
    return records[0].id


def test_list_accounts_empty(client):
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_list_accounts_after_create(client):
    _create_account()
    resp = client.get("/api/accounts")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["email"] == "test@example.com"


def test_get_account_by_id(client):
    account_id = _create_account()
    resp = client.get(f"/api/accounts/{account_id}")
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@example.com"


def test_get_account_not_found(client):
    resp = client.get("/api/accounts/99999")
    assert resp.status_code == 404


def test_delete_account(client):
    account_id = _create_account()
    del_resp = client.delete(f"/api/accounts/{account_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True
    # Verify it's gone
    get_resp = client.get(f"/api/accounts/{account_id}")
    assert get_resp.status_code == 404


def test_update_account(client):
    account_id = _create_account()
    patch_resp = client.patch(
        f"/api/accounts/{account_id}",
        json={"password": "NewPass456!"},
    )
    assert patch_resp.status_code == 200


def test_filter_accounts_by_platform(client):
    _create_account(platform="chatgpt", email="a@test.com")
    _create_account(platform="cursor", email="b@test.com")
    resp = client.get("/api/accounts", params={"platform": "cursor"})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["platform"] == "cursor"


def test_account_stats(client):
    _create_account()
    resp = client.get("/api/accounts/stats")
    assert resp.status_code == 200


def test_export_any2api_multi_platform(client):
    _create_account(platform="kiro", email="k@test.com", password="")
    _create_account(platform="grok", email="g@test.com", password="")
    _create_account(platform="cursor", email="c@test.com", password="")
    resp = client.post("/api/accounts/export/any2api", json={"select_all": True})
    assert resp.status_code == 200
    assert "any2api_admin" in resp.headers.get("content-disposition", "")


def test_export_cpa_uses_standard_payload_schema():
    exp_timestamp = 1777166030
    expected_expired = datetime.fromtimestamp(
        exp_timestamp, tz=timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    access_token = _make_jwt({
        "exp": exp_timestamp,
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct-standard",
        },
    })
    id_token = _make_jwt({
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct-standard",
        },
    })
    repository = AccountsRepository()
    save_account(
        Account(
            platform="chatgpt",
            email="cpa@test.com",
            password="TestPass123!",
            user_id="acct-standard",
            extra={
                "access_token": access_token,
                "refresh_token": "rt_standard",
                "id_token": id_token,
            },
        )
    )
    service = AccountExportsService(repository)

    artifact = service.export_chatgpt_cpa(AccountExportSelection(platform="chatgpt", select_all=True))
    payload = json.loads(artifact.content)
    assert list(payload.keys()) == [
        "access_token",
        "account_id",
        "email",
        "expired",
        "id_token",
        "last_refresh",
        "refresh_token",
        "type",
    ]
    assert payload["access_token"] == access_token
    assert payload["account_id"] == "acct-standard"
    assert payload["email"] == "cpa@test.com"
    assert payload["expired"] == expected_expired
    assert payload["id_token"] == id_token
    assert payload["last_refresh"].endswith("+08:00")
    assert payload["refresh_token"] == "rt_standard"
    assert payload["type"] == "codex"


def test_export_cpa_falls_back_to_stored_user_id_for_account_id():
    repository = AccountsRepository()
    save_account(
        Account(
            platform="chatgpt",
            email="fallback@test.com",
            password="TestPass123!",
            user_id="acct-from-user-id",
            extra={
                "access_token": _make_jwt({"exp": 1777166030}),
                "refresh_token": "rt_fallback",
            },
        )
    )
    service = AccountExportsService(repository)

    artifact = service.export_chatgpt_cpa(AccountExportSelection(platform="chatgpt", select_all=True))
    payload = json.loads(artifact.content)
    assert payload["account_id"] == "acct-from-user-id"
    assert payload["refresh_token"] == "rt_fallback"


def test_export_agent_identity_sub2api_registers_from_stored_tokens(monkeypatch):
    id_token = _make_jwt({
        "email": "identity@test.com",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct-identity",
            "chatgpt_user_id": "user-identity",
            "chatgpt_plan_type": "free",
        },
    })
    access_token = _make_jwt({"exp": 1777166030})
    save_account(
        Account(
            platform="chatgpt",
            email="identity@test.com",
            password="TestPass123!",
            user_id="acct-identity",
            extra={"access_token": access_token, "id_token": id_token},
        )
    )

    captured = {}

    def fake_register_identity(tokens, *, auth_api_base_url, codex_base_url):
        captured["tokens"] = tokens
        captured["auth_api_base_url"] = auth_api_base_url
        captured["codex_base_url"] = codex_base_url
        return {
            "private_key_seed": base64.b64encode(b"x" * 32).decode("ascii"),
            "agent_runtime_id": "runtime-identity",
            "task_id": "task-identity",
            "account_id": "acct-identity",
            "chatgpt_user_id": "user-identity",
            "email": "identity@test.com",
            "plan_type": "free",
            "chatgpt_account_is_fedramp": False,
        }

    monkeypatch.setattr(
        "platforms.chatgpt.from_credentials.register_identity",
        fake_register_identity,
    )

    artifact = AccountExportsService(AccountsRepository()).export_chatgpt_agent_identity_sub2api(
        AccountExportSelection(platform="chatgpt", select_all=True)
    )
    payload = json.loads(artifact.content)
    identity = payload["agent_identity"]

    assert artifact.filename == "identity@test.com_agent_identity_sub2api.json"
    assert captured["tokens"] == {
        "access_token": access_token,
        "id_token": id_token,
    }
    assert payload["auth_mode"] == "agentIdentity"
    assert payload["OPENAI_API_KEY"] is None
    assert payload["type"] == "sub2api-data"
    assert payload["version"] == 1
    assert payload["proxies"] == []
    assert payload["accounts"][0]["credentials"]["auth_mode"] == "agentIdentity"
    assert payload["accounts"][0]["credentials"]["chatgpt_account_id"] == "acct-identity"
    assert identity["agent_runtime_id"] == "runtime-identity"
    assert identity["task_id"] == "task-identity"
    assert identity["account_id"] == "acct-identity"
    assert identity["agent_private_key"]


def test_export_agent_identity_sub2api_falls_back_to_access_token_claims(monkeypatch):
    access_token = _make_jwt({
        "email": "access-claims@test.com",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct-access-claims",
            "chatgpt_user_id": "user-access-claims",
        },
    })
    save_account(
        Account(
            platform="chatgpt",
            email="access-claims@test.com",
            password="TestPass123!",
            extra={"access_token": access_token},
        )
    )

    captured = {}

    def fake_register_identity(tokens, *, auth_api_base_url, codex_base_url):
        captured["tokens"] = tokens
        return {
            "private_key_seed": base64.b64encode(b"y" * 32).decode("ascii"),
            "agent_runtime_id": "runtime-access-claims",
            "task_id": "task-access-claims",
            "account_id": "acct-access-claims",
            "chatgpt_user_id": "user-access-claims",
            "email": "access-claims@test.com",
            "plan_type": "free",
            "chatgpt_account_is_fedramp": False,
        }

    monkeypatch.setattr(
        "platforms.chatgpt.from_credentials.register_identity",
        fake_register_identity,
    )

    service = AccountExportsService(AccountsRepository())
    artifact = service.export_chatgpt_agent_identity_sub2api(
        AccountExportSelection(platform="chatgpt", select_all=True)
    )
    payload = json.loads(artifact.content)

    assert captured["tokens"] == {
        "access_token": access_token,
        "id_token": access_token,
    }
    assert payload["auth_mode"] == "agentIdentity"
    assert payload["agent_identity"]["account_id"] == "acct-access-claims"
    assert payload["accounts"][0]["credentials"]["auth_mode"] == "agentIdentity"


def test_export_agent_identity_sub2api_requires_identity_claims():
    save_account(
        Account(
            platform="chatgpt",
            email="missing-claims@test.com",
            password="TestPass123!",
            extra={"access_token": _make_jwt({"exp": 1777166030})},
        )
    )

    service = AccountExportsService(AccountsRepository())
    try:
        service.export_chatgpt_agent_identity_sub2api(
            AccountExportSelection(platform="chatgpt", select_all=True)
        )
    except ValueError as exc:
        assert "claims" in str(exc)
    else:
        raise AssertionError("OAuth tokens without identity claims should be rejected")
