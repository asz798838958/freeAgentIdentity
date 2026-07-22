from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class AccountRecord:
    id: int
    platform: str
    email: str
    password: str
    user_id: str = ""
    primary_token: str = ""
    trial_end_time: int = 0
    cashier_url: str = ""
    lifecycle_status: str = "registered"
    validity_status: str = "unknown"
    plan_state: str = "unknown"
    plan_name: str = ""
    display_status: str = "registered"
    overview: dict = field(default_factory=dict)
    display_summary: dict = field(default_factory=dict)
    credentials: list[dict] = field(default_factory=list)
    provider_accounts: list[dict] = field(default_factory=list)
    provider_resources: list[dict] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(slots=True)
class AccountQuery:
    platform: str = ""
    status: str = ""
    email: str = ""
    page: int = 1
    page_size: int = 20


@dataclass(slots=True)
class AccountUpdateCommand:
    password: Optional[str] = None
    user_id: Optional[str] = None
    lifecycle_status: Optional[str] = None
    overview: Optional[dict] = None
    credentials: Optional[dict] = None
    provider_accounts: Optional[list[dict]] = None
    provider_resources: Optional[list[dict]] = None
    replace_provider_accounts: bool = False
    replace_provider_resources: bool = False
    primary_token: Optional[str] = None
    cashier_url: Optional[str] = None
    region: Optional[str] = None
    trial_end_time: Optional[int] = None


@dataclass(slots=True)
class AccountImportLine:
    email: str
    password: str
    extra: dict = field(default_factory=dict)


@dataclass(slots=True)
class AccountStats:
    total: int
    by_platform: dict[str, int]
    by_status: dict[str, int]
    by_lifecycle_status: dict[str, int] = field(default_factory=dict)
    by_plan_state: dict[str, int] = field(default_factory=dict)
    by_validity_status: dict[str, int] = field(default_factory=dict)
    by_display_status: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class AccountExportSelection:
    platform: str = ""
    ids: list[int] = field(default_factory=list)
    select_all: bool = False
    status_filter: str = ""
    search_filter: str = ""
