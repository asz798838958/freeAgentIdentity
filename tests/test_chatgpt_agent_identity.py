from __future__ import annotations

import base64

from platforms.chatgpt.from_credentials import (
    certificate_to_sub2api_export,
    get_thread_proxy_url,
    set_thread_proxy_url,
)


def test_explicit_empty_proxy_disables_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://environment-proxy.test:8080")
    set_thread_proxy_url("")
    try:
        assert get_thread_proxy_url() is None
    finally:
        set_thread_proxy_url(None)


def test_proxy_falls_back_to_environment_without_thread_override(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://environment-proxy.test:8080")
    set_thread_proxy_url(None)
    assert get_thread_proxy_url() == "http://environment-proxy.test:8080"


def test_sub2api_export_uses_direct_agent_identity_auth_json():
    payload = certificate_to_sub2api_export(
        {
            "private_key_seed": base64.b64encode(b"z" * 32).decode("ascii"),
            "agent_runtime_id": "agent-test",
            "task_id": "task-test",
            "account_id": "account-test",
            "chatgpt_user_id": "user-test",
            "email": "identity@test.com",
            "plan_type": "free",
            "chatgpt_account_is_fedramp": False,
        }
    )

    assert payload["auth_mode"] == "agentIdentity"
    assert payload["OPENAI_API_KEY"] is None
    assert payload["agent_identity"]["account_id"] == "account-test"
    assert payload["agent_identity"]["agent_private_key"]
    assert payload["type"] == "sub2api-data"
    assert payload["version"] == 1
    assert payload["proxies"] == []
    assert payload["accounts"][0]["credentials"]["auth_mode"] == "agentIdentity"
    assert payload["accounts"][0]["credentials"]["chatgpt_account_id"] == "account-test"
