from __future__ import annotations

from application.provider_definitions import ProviderDefinitionsService
from application.platforms import PlatformsService, collect_platform_choice_options
from application.provider_settings import ProviderSettingsService
from infrastructure.config_repository import ConfigRepository


class ConfigService:
    def __init__(self, repository: ConfigRepository | None = None):
        self.repository = repository or ConfigRepository()
        self.provider_definitions = ProviderDefinitionsService()
        self.provider_settings = ProviderSettingsService()
        self.platforms = PlatformsService()

    def get_config(self) -> dict[str, str]:
        return self.repository.get_flat()

    def update_config(self, data: dict[str, str]) -> dict:
        updated = self.repository.update_flat(data)
        return {"ok": True, "updated": updated}

    def get_options(self) -> dict:
        platform_options = collect_platform_choice_options(
            [item for item in self.platforms.list_platforms() if item.get("name") == "chatgpt"]
        )
        return {
            "mailbox_providers": self.provider_definitions.list_definitions("mailbox", enabled_only=True),
            "captcha_providers": self.provider_definitions.list_definitions("captcha", enabled_only=True),
            "mailbox_drivers": self.provider_definitions.list_driver_templates("mailbox"),
            "captcha_drivers": self.provider_definitions.list_driver_templates("captcha"),
            "captcha_policy": self.provider_settings.get_captcha_policy(),
            "mailbox_settings": self.provider_settings.list_settings("mailbox"),
            "captcha_settings": self.provider_settings.list_settings("captcha"),
            **platform_options,
        }
