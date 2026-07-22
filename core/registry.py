"""当前界面所需的平台插件注册表。"""
import importlib
from typing import Dict, Type
from .base_platform import BasePlatform

_registry: Dict[str, Type[BasePlatform]] = {}

def register(cls: Type[BasePlatform]):
    """装饰器：注册平台插件"""
    _registry[cls.name] = cls
    return cls


def load_all():
    """只加载当前仪表盘仍会展示的平台。"""
    for name in ("chatgpt", "cursor", "kiro"):
        importlib.import_module(f"platforms.{name}.plugin")


def get(name: str) -> Type[BasePlatform]:
    if name not in _registry:
        raise KeyError(f"平台 '{name}' 未注册，已注册: {list(_registry.keys())}")
    return _registry[name]


def _class_defaults(cls: Type[BasePlatform]) -> dict[str, list[str]]:
    """从类属性获取 fallback 默认值（仅在 DB 无数据时使用）。"""
    return {
        "supported_executors": list(getattr(cls, "supported_executors", [])),
        "supported_identity_modes": list(getattr(cls, "supported_identity_modes", [])),
        "supported_oauth_providers": list(getattr(cls, "supported_oauth_providers", [])),
        "capabilities": list(getattr(cls, "capabilities", [])),
    }


def get_platform_capabilities(name: str) -> dict[str, list[str]]:
    return _class_defaults(get(name))


def list_platforms() -> list:
    return [
        {
            "name": cls.name,
            "display_name": cls.display_name,
            "version": cls.version,
            **_class_defaults(cls),
        }
        for cls in _registry.values()
    ]
