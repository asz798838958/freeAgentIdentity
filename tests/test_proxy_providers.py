"""Dynamic proxy provider unit tests."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from core.proxy_providers import (
    ApiExtractProvider,
    RotatingProxyProvider,
    create_proxy_provider,
)


class TestApiExtractProvider:
    def test_parse_plain_text(self):
        provider = ApiExtractProvider(api_url="http://fake")
        lines = "1.2.3.4:8080\n5.6.7.8:3128\n"
        mock_resp = MagicMock()
        mock_resp.text = lines
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("core.proxy_providers.requests.get", return_value=mock_resp):
            proxy = provider.get_proxy()
            assert proxy == "http://1.2.3.4:8080"
            proxy2 = provider.get_proxy()
            assert proxy2 == "http://5.6.7.8:3128"
            # Cache exhausted
            proxy3 = provider.get_proxy()
            # Will re-fetch
            assert proxy3 is not None

    def test_parse_json_array(self):
        provider = ApiExtractProvider(api_url="http://fake")
        mock_resp = MagicMock()
        mock_resp.text = json.dumps(["10.0.0.1:1080", "10.0.0.2:1080"])
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("core.proxy_providers.requests.get", return_value=mock_resp):
            proxy = provider.get_proxy()
            assert "10.0.0.1:1080" in proxy

    def test_parse_json_object_with_data_key(self):
        provider = ApiExtractProvider(api_url="http://fake")
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"data": ["10.0.0.1:8080"]})
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("core.proxy_providers.requests.get", return_value=mock_resp):
            proxy = provider.get_proxy()
            assert "10.0.0.1:8080" in proxy

    def test_with_auth(self):
        provider = ApiExtractProvider(
            api_url="http://fake",
            username="user",
            password="pass",
        )
        mock_resp = MagicMock()
        mock_resp.text = "1.2.3.4:8080"
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("core.proxy_providers.requests.get", return_value=mock_resp):
            proxy = provider.get_proxy()
            assert proxy == "http://user:pass@1.2.3.4:8080"

    def test_with_socks5_protocol(self):
        provider = ApiExtractProvider(
            api_url="http://fake",
            protocol="socks5",
        )
        mock_resp = MagicMock()
        mock_resp.text = "1.2.3.4:1080"
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("core.proxy_providers.requests.get", return_value=mock_resp):
            proxy = provider.get_proxy()
            assert proxy == "socks5://1.2.3.4:1080"

    def test_already_has_protocol(self):
        provider = ApiExtractProvider(api_url="http://fake")
        mock_resp = MagicMock()
        mock_resp.text = "socks5://1.2.3.4:1080"
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        with patch("core.proxy_providers.requests.get", return_value=mock_resp):
            proxy = provider.get_proxy()
            assert proxy == "socks5://1.2.3.4:1080"

    def test_api_failure_returns_none(self):
        provider = ApiExtractProvider(api_url="http://fake")
        with patch("core.proxy_providers.requests.get", side_effect=Exception("timeout")):
            proxy = provider.get_proxy()
            assert proxy is None


class TestRotatingProxyProvider:
    def test_returns_gateway(self):
        provider = RotatingProxyProvider(gateway_url="http://user:pass@gate.example.com:8080")
        assert provider.get_proxy() == "http://user:pass@gate.example.com:8080"
        # Always returns the same gateway
        assert provider.get_proxy() == "http://user:pass@gate.example.com:8080"

    def test_empty_gateway(self):
        provider = RotatingProxyProvider(gateway_url="")
        assert provider.get_proxy() is None


class TestCreateProxyProvider:
    def test_api_extract(self):
        provider = create_proxy_provider("api_extract", {"proxy_api_url": "http://api.test/get"})
        assert isinstance(provider, ApiExtractProvider)

    def test_rotating_gateway(self):
        provider = create_proxy_provider("rotating_gateway", {"proxy_gateway_url": "http://gate:8080"})
        assert isinstance(provider, RotatingProxyProvider)

    def test_api_extract_missing_url(self):
        with pytest.raises(RuntimeError, match="未配置"):
            create_proxy_provider("api_extract", {})

    def test_rotating_missing_gateway(self):
        with pytest.raises(RuntimeError, match="未配置"):
            create_proxy_provider("rotating_gateway", {})

    def test_unknown_provider(self):
        with pytest.raises(RuntimeError, match="未知"):
            create_proxy_provider("unknown", {})
