from __future__ import annotations

from application.tasks import _resolve_registration_proxy_for_platform


def test_chatgpt_registration_uses_explicit_proxy_without_proxy_pool():
    calls = []
    proxy = _resolve_registration_proxy_for_platform(
        "chatgpt",
        explicit_proxy="http://explicit-proxy.example:8080",
        proxy_getter=lambda: calls.append("called") or "http://pool-proxy.example:8080",
    )
    assert proxy == "http://explicit-proxy.example:8080"
    assert calls == []


def test_chatgpt_registration_uses_local_network_when_proxy_is_blank():
    calls = []
    proxy = _resolve_registration_proxy_for_platform(
        "chatgpt",
        explicit_proxy="  ",
        proxy_getter=lambda: calls.append("called") or "http://pool-proxy.example:8080",
    )
    assert proxy is None
    assert calls == []
