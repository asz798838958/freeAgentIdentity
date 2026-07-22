from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ActionParameter:
    key: str
    label: str
    type: str
    options: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlatformAction:
    id: str
    label: str
    params: list[ActionParameter] = field(default_factory=list)
    sync: bool = False


@dataclass(slots=True)
class ActionExecutionCommand:
    platform: str
    account_id: int
    action_id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionExecutionResult:
    ok: bool
    data: Any = None
    error: str = ""
