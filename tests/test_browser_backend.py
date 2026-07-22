"""Tests for BitBrowser client + browser-backend dispatcher.

Coverage focus:
  * BitBrowserClient parsing of multiple BitBrowser API response shapes.
  * BitBrowserClient error paths (connection refused, non-JSON, missing data).
  * BrowserBackendConfig validation rules.
  * parse_checkout_mode string-to-config translation.
  * open_browser_backend dispatch (camoufox vs BitBrowser).

Every HTTP boundary is monkey-patched. End-to-end PayPal flow is
exercised manually by the user.
"""

from __future__ import annotations

import json

import pytest

from platforms import _bitbrowser as bb
from platforms import _browser_backend as bbe


class _FakeResponse:
    def __init__(self, payload, *, status_code=200, raise_json=False):
        self._payload = payload
        self.status_code = status_code
        self._raise_json = raise_json
        self.text = "not-json" if raise_json else json.dumps(payload)

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _patch_post(monkeypatch, fn):
    monkeypatch.setattr(bb.requests, "post", fn)


def _patch_get(monkeypatch, fn):
    monkeypatch.setattr(bb.requests, "get", fn)


def test_bitbrowser_client_open_parses_ws_field(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResponse(
            {"success": True, "data": {"ws": "ws://127.0.0.1:6000/devtools/browser/abc"}}
        )

    _patch_post(monkeypatch, fake_post)
    client = bb.BitBrowserClient(api_url="http://127.0.0.1:54345")

    result = client.open("profile-1", args=["--headless=new"])

    assert result.profile_id == "profile-1"
    assert result.ws_endpoint == "ws://127.0.0.1:6000/devtools/browser/abc"
    assert captured["url"].endswith("/browser/open")
    assert captured["payload"]["id"] == "profile-1"
    assert captured["payload"]["args"] == ["--headless=new"]


def test_bitbrowser_client_open_accepts_code_zero_shape(monkeypatch):
    def fake_post(url, **_):
        return _FakeResponse(
            {
                "code": 0,
                "data": {
                    "webSocketDebuggerUrl": "ws://127.0.0.1:6001/devtools/browser/xyz",
                    "debuggerAddress": "127.0.0.1:6001",
                },
            }
        )

    _patch_post(monkeypatch, fake_post)
    client = bb.BitBrowserClient()

    result = client.open("p2")
    assert result.ws_endpoint.startswith("ws://127.0.0.1:6001/")
    assert result.http_endpoint == "127.0.0.1:6001"


def test_bitbrowser_client_open_http_fallback_fetches_ws_from_json_version(monkeypatch):
    def fake_post(url, **_):
        return _FakeResponse({"success": True, "data": {"http": "http://127.0.0.1:6002"}})

    def fake_get(url, timeout=None):
        assert url == "http://127.0.0.1:6002/json/version"
        return _FakeResponse(
            {"webSocketDebuggerUrl": "ws://127.0.0.1:6002/devtools/browser/aaa"}
        )

    _patch_post(monkeypatch, fake_post)
    _patch_get(monkeypatch, fake_get)
    client = bb.BitBrowserClient()

    result = client.open("p3")
    assert result.ws_endpoint == "ws://127.0.0.1:6002/devtools/browser/aaa"


def test_bitbrowser_client_open_rejects_empty_profile_id(monkeypatch):
    client = bb.BitBrowserClient()
    with pytest.raises(bb.BitBrowserError, match="profile_id"):
        client.open("   ")


def test_bitbrowser_client_open_raises_on_connection_error(monkeypatch):
    import requests as real_requests

    def fake_post(*_a, **_k):
        raise real_requests.exceptions.ConnectionError("no listener")

    _patch_post(monkeypatch, fake_post)
    client = bb.BitBrowserClient()

    with pytest.raises(bb.BitBrowserError, match="无法连接"):
        client.open("p4")


def test_bitbrowser_client_open_raises_on_non_json_body(monkeypatch):
    def fake_post(url, **_):
        return _FakeResponse(None, raise_json=True)

    _patch_post(monkeypatch, fake_post)
    client = bb.BitBrowserClient()

    with pytest.raises(bb.BitBrowserError, match="非 JSON"):
        client.open("p5")


def test_bitbrowser_client_open_raises_when_success_false(monkeypatch):
    def fake_post(url, **_):
        return _FakeResponse({"success": False, "msg": "profile in use"})

    _patch_post(monkeypatch, fake_post)
    client = bb.BitBrowserClient()

    with pytest.raises(bb.BitBrowserError, match="profile in use"):
        client.open("p6")


def test_bitbrowser_client_open_raises_when_no_ws_endpoint(monkeypatch):
    def fake_post(url, **_):
        return _FakeResponse({"success": True, "data": {"foo": "bar"}})

    _patch_post(monkeypatch, fake_post)
    client = bb.BitBrowserClient()

    with pytest.raises(bb.BitBrowserError, match="ws endpoint"):
        client.open("p7")


def test_bitbrowser_client_close_swallows_errors(monkeypatch):
    """close() must never raise — clean-up paths rely on this."""

    def fake_post(url, **_):
        return _FakeResponse({"success": False, "msg": "not found"})

    _patch_post(monkeypatch, fake_post)
    client = bb.BitBrowserClient()
    # Should silently swallow the error
    client.close("missing-id")


# ---------------------------------------------------------------------------
# BrowserBackendConfig
# ---------------------------------------------------------------------------


def test_backend_config_camoufox_factory_sets_window_mode_from_headless():
    cfg = bbe.BrowserBackendConfig.camoufox(headless=True)
    assert cfg.is_camoufox
    assert cfg.is_headless
    assert cfg.window_mode == "headless"

    cfg2 = bbe.BrowserBackendConfig.camoufox(headless=False)
    assert cfg2.window_mode == "headed"
    assert not cfg2.is_headless


def test_backend_config_bitbrowser_factory_requires_profile_id():
    with pytest.raises(ValueError, match="bit_profile_id"):
        bbe.BrowserBackendConfig.bitbrowser(profile_id="", window_mode="hidden")


def test_backend_config_bitbrowser_factory_records_all_fields():
    cfg = bbe.BrowserBackendConfig.bitbrowser(
        profile_id="abc",
        window_mode="hidden",
        api_url="http://example.com:54345",
        api_token="token-xyz",
    )
    assert cfg.is_bitbrowser
    assert cfg.window_mode == "hidden"
    assert cfg.bit_profile_id == "abc"
    assert cfg.bit_api_url == "http://example.com:54345"
    assert cfg.bit_api_token == "token-xyz"


def test_backend_config_camoufox_with_hidden_is_coerced_to_headed():
    """Camoufox doesn't have a hidden mode; we silently coerce hidden→headed."""
    cfg = bbe.BrowserBackendConfig(backend="camoufox", window_mode="hidden")
    assert cfg.window_mode == "headed"


def test_backend_config_rejects_unknown_backend():
    with pytest.raises(ValueError, match="未识别的 backend"):
        bbe.BrowserBackendConfig(backend="firefox", window_mode="headed")


def test_backend_config_rejects_unknown_window_mode():
    with pytest.raises(ValueError, match="window_mode"):
        bbe.BrowserBackendConfig(backend="camoufox", window_mode="invisible")


# ---------------------------------------------------------------------------
# parse_checkout_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode, expected_backend, expected_window",
    [
        ("camoufox_headed", "camoufox", "headed"),
        ("camoufox_headless", "camoufox", "headless"),
        ("bitbrowser_headed", "bitbrowser", "headed"),
        ("bitbrowser_hidden", "bitbrowser", "hidden"),
        ("bitbrowser_headless", "bitbrowser", "headless"),
        ("", "camoufox", "headed"),
        ("nonsense_value", "camoufox", "headed"),
    ],
)
def test_parse_checkout_mode_matrix(mode, expected_backend, expected_window):
    if expected_backend == "bitbrowser":
        cfg = bbe.parse_checkout_mode(mode, bit_profile_id="abc")
    else:
        cfg = bbe.parse_checkout_mode(mode)
    assert cfg.backend == expected_backend
    assert cfg.window_mode == expected_window


def test_parse_checkout_mode_bitbrowser_without_profile_id_raises():
    with pytest.raises(ValueError):
        bbe.parse_checkout_mode("bitbrowser_hidden", bit_profile_id="")


# ---------------------------------------------------------------------------
# open_browser_backend dispatcher
# ---------------------------------------------------------------------------


class _FakeCamoufoxClass:
    """Stand-in for camoufox.sync_api.Camoufox so we can verify launch_opts pass-through."""

    last_kwargs = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)
        self.kwargs = kwargs

    def __enter__(self):
        return "camoufox-browser"

    def __exit__(self, *args):
        return False


def test_open_browser_backend_camoufox_path_passes_launch_opts():
    cfg = bbe.BrowserBackendConfig.camoufox(headless=False)
    launch_opts = {"headless": False, "block_webrtc": True, "locale": ["en-US", "en"]}

    ctx = bbe.open_browser_backend(
        launch_opts=launch_opts,
        config=cfg,
        camoufox_class=_FakeCamoufoxClass,
        log=lambda _msg: None,
    )

    assert isinstance(ctx, _FakeCamoufoxClass)
    assert ctx.kwargs == launch_opts


def test_open_browser_backend_camoufox_missing_class_raises():
    cfg = bbe.BrowserBackendConfig.camoufox(headless=False)
    with pytest.raises(RuntimeError, match="Camoufox 不可用"):
        bbe.open_browser_backend(
            launch_opts={"headless": False},
            config=cfg,
            camoufox_class=None,
            log=lambda _msg: None,
        )


def test_open_browser_backend_bitbrowser_path_returns_bitbrowser_context(monkeypatch):
    """Dispatcher must instantiate BitBrowserContext (no actual API call here)."""
    cfg = bbe.BrowserBackendConfig.bitbrowser(profile_id="abc", window_mode="hidden")

    captured = {}

    class _StubBitBrowserContext:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(bbe, "BitBrowserContext", _StubBitBrowserContext)

    ctx = bbe.open_browser_backend(
        launch_opts={"headless": False},
        config=cfg,
        camoufox_class=_FakeCamoufoxClass,  # ignored on bitbrowser path
        log=lambda _msg: None,
    )

    assert isinstance(ctx, _StubBitBrowserContext)
    assert captured["profile_id"] == "abc"
    assert captured["window_mode"] == "hidden"
    assert captured["api_url"] == bb.DEFAULT_BIT_API_URL


# ---------------------------------------------------------------------------
# BitBrowserContext (window mode args + cleanup on connection failure)
# ---------------------------------------------------------------------------


def test_bitbrowser_context_build_args_per_window_mode():
    """Each window mode adds the correct Chromium flag (or none)."""

    headed = bb.BitBrowserContext(profile_id="x", window_mode="headed")
    assert headed._build_args() == []

    hidden = bb.BitBrowserContext(profile_id="x", window_mode="hidden")
    assert hidden._build_args() == ["--window-position=-32000,-32000"]

    headless = bb.BitBrowserContext(profile_id="x", window_mode="headless")
    assert headless._build_args() == ["--headless=new"]


def test_bitbrowser_context_rejects_unknown_window_mode():
    with pytest.raises(bb.BitBrowserError, match="window_mode"):
        bb.BitBrowserContext(profile_id="x", window_mode="invisible")


def test_bitbrowser_context_rejects_empty_profile_id():
    with pytest.raises(bb.BitBrowserError, match="profile_id"):
        bb.BitBrowserContext(profile_id="   ")
