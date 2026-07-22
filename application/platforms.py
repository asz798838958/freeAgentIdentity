from __future__ import annotations

from infrastructure.platform_runtime import PlatformRuntime


EXECUTOR_LABELS = {
    "protocol": "协议模式",
    "headless": "后台浏览器自动",
    "headed": "可视浏览器自动",
}

IDENTITY_MODE_LABELS = {
    "mailbox": "系统邮箱",
}


def _choice_options(values: list[str], labels: dict[str, str]) -> list[dict]:
    return [
        {"value": value, "label": labels.get(value, value)}
        for value in values
        if str(value or "").strip()
    ]


def collect_platform_choice_options(platforms: list[dict]) -> dict[str, list[dict]]:
    executor_values: list[str] = []
    identity_values: list[str] = []
    for item in platforms:
        for value in item.get("supported_executors", []) or []:
            if value not in executor_values:
                executor_values.append(value)
        for value in item.get("supported_identity_modes", []) or []:
            if value not in identity_values:
                identity_values.append(value)
    return {
        "executor_options": _choice_options(executor_values, EXECUTOR_LABELS),
        "identity_mode_options": _choice_options(identity_values, IDENTITY_MODE_LABELS),
    }


class PlatformsService:
    def __init__(self, runtime: PlatformRuntime | None = None):
        self.runtime = runtime or PlatformRuntime()

    def list_platforms(self) -> list[dict]:
        result = []
        for item in self.runtime.list_platforms():
            result.append(
                {
                    "name": item.name,
                    "display_name": item.display_name,
                    "version": item.version,
                    "supported_executors": item.capabilities.supported_executors,
                    "supported_identity_modes": item.capabilities.supported_identity_modes,
                    "supported_oauth_providers": item.capabilities.supported_oauth_providers,
                    "supported_executor_options": _choice_options(item.capabilities.supported_executors, EXECUTOR_LABELS),
                    "supported_identity_mode_options": _choice_options(item.capabilities.supported_identity_modes, IDENTITY_MODE_LABELS),
                }
            )
        return result

    def get_desktop_state(self, platform: str) -> dict:
        return self.runtime.get_desktop_state(platform)
