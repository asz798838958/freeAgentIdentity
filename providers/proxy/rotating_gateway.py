"""Rotating gateway proxy provider — fixed entry with rotating exit IPs."""
from __future__ import annotations

from typing import Optional

from core.proxy_providers import BaseProxyProvider
from providers.registry import register_provider


@register_provider("proxy", "rotating_gateway")
class RotatingProxyProvider(BaseProxyProvider):
    """固定入口旋转代理 — 每次请求自动分配不同 IP。

    适用于提供固定网关地址的代理商（如 BrightData、Oxylabs、IPRoyal 等），
    格式通常是: http://user:pass@gate.provider.com:port
    每次通过该网关发出的请求会自动使用不同的出口 IP。
    """

    def __init__(self, *, gateway_url: str):
        self.gateway_url = gateway_url

    @classmethod
    def from_config(cls, config: dict) -> 'RotatingProxyProvider':
        gateway = config.get("proxy_gateway_url", "")
        if not gateway:
            raise RuntimeError("旋转代理未配置网关地址")
        return cls(gateway_url=gateway)

    def get_proxy(self) -> Optional[str]:
        return self.gateway_url if self.gateway_url else None
