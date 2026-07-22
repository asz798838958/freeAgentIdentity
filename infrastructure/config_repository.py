from __future__ import annotations

from core.config_store import config_store
from infrastructure.provider_definitions_repository import ProviderDefinitionsRepository


class ConfigRepository:
    BASE_KEYS = {
        "default_executor",
        "default_identity_provider",
        "cpa_api_url", "cpa_api_key",
        "team_manager_url", "team_manager_key",
    }

    def __init__(self, definitions: ProviderDefinitionsRepository | None = None):
        self.definitions = definitions or ProviderDefinitionsRepository()

    def get_allowed_keys(self) -> set[str]:
        keys = set(self.BASE_KEYS)
        for provider_type in ("mailbox", "captcha"):
            for definition in self.definitions.list_by_type(provider_type, enabled_only=False):
                for field in definition.get_fields():
                    field_key = str(field.get("key") or "").strip()
                    if field_key:
                        keys.add(field_key)
        return keys

    def get_flat(self) -> dict[str, str]:
        data = config_store.get_all()
        allowed = self.get_allowed_keys()
        return {
            key: str(value or "")
            for key, value in data.items()
            if key in allowed
        }

    def update_flat(self, data: dict[str, str]) -> list[str]:
        allowed = self.get_allowed_keys()
        safe = {key: value for key, value in data.items() if key in allowed}
        config_store.set_many(safe)
        return list(safe.keys())
