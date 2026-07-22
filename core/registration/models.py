from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class RegistrationCapability:
    oauth_allowed_executor_types: tuple[str, ...] | None = None
    oauth_headless_requires_browser_reuse: bool = False
    browser_mailbox_requires_email: bool = True
    browser_mailbox_requires_mailbox: bool = True
    protocol_mailbox_requires_email: bool = True
    protocol_mailbox_requires_mailbox: bool = True


@dataclass(slots=True)
class RegistrationContext:
    platform_name: str
    platform_display_name: str
    platform: Any
    identity: Any
    config: Any
    email: str | None
    password: str | None
    log_fn: Callable[[str], None]

    @property
    def executor_type(self) -> str:
        return str(getattr(self.config, "executor_type", "") or "protocol")

    @property
    def proxy(self) -> str | None:
        return getattr(self.config, "proxy", None)

    @property
    def extra(self) -> dict[str, Any]:
        return dict(getattr(self.config, "extra", {}) or {})

    def log(self, message: str) -> None:
        self.log_fn(message)


@dataclass(slots=True)
class RegistrationArtifacts:
    otp_callback: Callable[[], str] | None = None
    verification_link_callback: Callable[[], str] | None = None
    captcha_solver: Any = None
    executor: Any = None
    raw_result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RegistrationResult:
    email: str
    password: str
    user_id: str = ""
    region: str = ""
    token: str = ""
    status: Any = None
    trial_end_time: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
