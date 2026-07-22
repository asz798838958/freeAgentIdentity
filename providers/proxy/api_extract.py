"""API extract proxy provider — fetch proxies from HTTP API."""
from __future__ import annotations

import logging
import re
import threading
from typing import Optional

import core.proxy_providers as proxy_providers
from core.proxy_providers import BaseProxyProvider
from providers.registry import register_provider

logger = logging.getLogger(__name__)


@register_provider("proxy", "api_extract")
class ApiExtractProvider(BaseProxyProvider):
    """通用 API 提取模式 — 调用一个 URL 返回代理 IP 列表。

    适用于大多数代理商的"API 提取"接口，返回格式通常是:
      - 每行一个 IP:PORT
      - 或 JSON 数组
    """

    def __init__(
        self,
        *,
        api_url: str,
        protocol: str = "http",
        username: str = "",
        password: str = "",
        timeout: int = 10,
    ):
        self.api_url = api_url
        self.protocol = protocol or "http"
        self.username = username
        self.password = password
        self.timeout = timeout
        self._cache: list[str] = []
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config: dict) -> 'ApiExtractProvider':
        api_url = config.get("proxy_api_url", "")
        if not api_url:
            raise RuntimeError("动态代理未配置 API URL")
        return cls(
            api_url=api_url,
            protocol=config.get("proxy_protocol", "http"),
            username=config.get("proxy_username", ""),
            password=config.get("proxy_password", ""),
        )

    def _fetch(self) -> list[str]:
        """从 API 获取代理列表。"""
        try:
            resp = proxy_providers.requests.get(self.api_url, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.text.strip()
        except Exception as exc:
            logger.warning(f"[ProxyProvider] API 请求失败: {exc}")
            return []

        # Try JSON first
        try:
            import json
            data = json.loads(text)
            if isinstance(data, list):
                return [self._normalize(str(item)) for item in data if item]
            if isinstance(data, dict):
                # Common patterns: {"data": [...], "proxies": [...], "list": [...]}
                for key in ("data", "proxies", "list", "proxy_list", "result"):
                    items = data.get(key)
                    if isinstance(items, list):
                        return [self._normalize(str(item)) for item in items if item]
        except (ValueError,):
            pass

        # Fall back to line-by-line parsing
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return [self._normalize(line) for line in lines if self._looks_like_proxy(line)]

    def _looks_like_proxy(self, line: str) -> bool:
        """Check if a line looks like a proxy address."""
        if line.startswith(("http://", "https://", "socks5://", "socks4://")):
            return True
        return bool(re.match(r'^[\w.\-]+:\d+', line))

    def _normalize(self, raw: str) -> str:
        """Normalize a raw proxy string to a full URL."""
        raw = raw.strip()
        if raw.startswith(("http://", "https://", "socks5://", "socks4://")):
            return raw
        # Add protocol and optional auth
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{raw}"
        return f"{self.protocol}://{raw}"

    def get_proxy(self) -> Optional[str]:
        with self._lock:
            if not self._cache:
                self._cache = self._fetch()
            if self._cache:
                return self._cache.pop(0)
        return None
