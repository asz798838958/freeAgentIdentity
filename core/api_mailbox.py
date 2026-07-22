"""Mailbox provider backed by per-address verification-code API URLs.

Each configured row has the form ``email----api_url``.  The URL is treated as
an opaque secret because it commonly contains the mailbox password or token in
its query string.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from core.base_mailbox import BaseMailbox, MailboxAccount, _extract_verification_link


DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / ".api_mailbox_pool_state.json"
DEFAULT_CODE_PATTERN = r"(?<!#)(?<!\d)(\d{6})(?!\d)"


@dataclass(frozen=True)
class ApiMailboxEntry:
    email: str
    api_url: str

    @property
    def key(self) -> str:
        return self.email.strip().lower()


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def parse_api_mailbox_rows(text: str) -> list[ApiMailboxEntry]:
    """Parse one ``email----api_url`` mailbox entry per line."""

    entries: list[ApiMailboxEntry] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip().strip("\ufeff")
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        email, separator, api_url = line.partition("----")
        email = email.strip()
        api_url = api_url.strip()
        if not separator or "@" not in email or not api_url:
            raise ValueError(f"API 邮箱第 {line_number} 行格式错误，应为：邮箱----完整 API URL")
        parsed = urlparse(api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"API 邮箱第 {line_number} 行 URL 无效，仅支持 http/https")
        entry = ApiMailboxEntry(email=email, api_url=api_url)
        if entry.key in seen:
            continue
        seen.add(entry.key)
        entries.append(entry)
    return entries


class ApiMailboxPool(BaseMailbox):
    """Use fixed email addresses and poll their individual API URLs for OTPs."""

    _lock = threading.Lock()

    def __init__(
        self,
        *,
        pool_text: str = "",
        state_file: str = "",
        allow_reuse: bool = False,
        poll_interval: float | str = 3,
        request_timeout: float | str = 15,
        proxy: str | None = None,
        session: requests.Session | None = None,
    ):
        self.pool_text = str(pool_text or "")
        self.state_file = Path(state_file or DEFAULT_STATE_FILE)
        self.allow_reuse = bool(allow_reuse)
        self.poll_interval = max(0.0, float(3 if poll_interval in (None, "") else poll_interval))
        self.request_timeout = max(1.0, float(15 if request_timeout in (None, "") else request_timeout))
        self.proxy = {"http": proxy, "https": proxy} if proxy else None
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, config: dict) -> "ApiMailboxPool":
        return cls(
            pool_text=config.get("api_mailbox_pool_text", ""),
            state_file=config.get("api_mailbox_state_file", ""),
            allow_reuse=_truthy(config.get("api_mailbox_allow_reuse")),
            poll_interval=config.get("api_mailbox_poll_interval", 3),
            request_timeout=config.get("api_mailbox_request_timeout", 15),
            proxy=config.get("proxy") or config.get("mailbox_proxy") or None,
        )

    def _entries(self) -> list[ApiMailboxEntry]:
        if not self.pool_text.strip():
            raise RuntimeError("API 邮箱池为空，请按“邮箱----完整 API URL”格式填写")
        entries = parse_api_mailbox_rows(self.pool_text)
        if not entries:
            raise RuntimeError("API 邮箱池未解析到有效邮箱")
        return entries

    def _state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {"used": {}}

    def _save_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _source_id(self) -> str:
        return hashlib.sha256(self.pool_text.encode("utf-8")).hexdigest()[:16]

    def _available_entry(self) -> ApiMailboxEntry:
        entries = self._entries()
        used = set((self._state().get("used") or {}).keys())
        for entry in entries:
            if self.allow_reuse or entry.key not in used:
                return entry
        raise RuntimeError(f"API 邮箱池已用尽: total={len(entries)}")

    def _reserve(self, entry: ApiMailboxEntry) -> None:
        if self.allow_reuse:
            return
        state = self._state()
        used = dict(state.get("used") or {})
        used[entry.key] = {
            "email": entry.email,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
            "source_id": self._source_id(),
        }
        state["used"] = used
        self._save_state(state)

    def peek_email(self) -> str:
        return self._available_entry().email

    def get_email(self) -> MailboxAccount:
        with self._lock:
            entry = self._available_entry()
            self._reserve(entry)
        return MailboxAccount(
            email=entry.email,
            account_id=entry.key,
            extra={
                "provider_account": {
                    "provider_type": "mailbox",
                    "provider_name": "api_mailbox",
                    "login_identifier": entry.email,
                    "display_name": entry.email,
                    "credentials": {"email": entry.email, "api_url": entry.api_url},
                    "metadata": {"source": "email_api_url"},
                },
                "provider_resource": {
                    "provider_type": "mailbox",
                    "provider_name": "api_mailbox",
                    "resource_type": "mailbox",
                    "resource_identifier": entry.key,
                    "handle": entry.email,
                    "display_name": entry.email,
                    "metadata": {
                        "email": entry.email,
                        "source": "email_api_url",
                        "reserved": not self.allow_reuse,
                    },
                },
            },
        )

    def _entry_for_account(self, account: MailboxAccount) -> ApiMailboxEntry:
        extra = dict(getattr(account, "extra", {}) or {})
        provider_account = dict(extra.get("provider_account") or {})
        credentials = dict(provider_account.get("credentials") or {})
        email = str(credentials.get("email") or account.email or "").strip()
        api_url = str(credentials.get("api_url") or "").strip()
        if email and api_url:
            return ApiMailboxEntry(email=email, api_url=api_url)
        account_key = str(account.email or "").strip().lower()
        for entry in self._entries():
            if entry.key == account_key:
                return entry
        raise RuntimeError(f"API 邮箱池未找到账号: {account.email}")

    def _request(self, entry: ApiMailboxEntry) -> tuple[object | None, str]:
        response = self.session.get(
            entry.api_url,
            headers={"Accept": "application/json, text/plain, */*", "User-Agent": "aBaiAutoplus/api-mailbox"},
            proxies=self.proxy,
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        raw = str(response.text or "").strip()
        try:
            payload = response.json()
        except Exception:
            payload = None
        return payload, raw

    @staticmethod
    def _match_code(value: object, pattern: re.Pattern[str]) -> str:
        match = pattern.search(str(value or ""))
        if not match:
            return ""
        return match.group(1) if match.groups() else match.group(0)

    @classmethod
    def _extract_code(cls, payload: object | None, raw: str, code_pattern: str | None = None) -> str:
        pattern = re.compile(code_pattern or DEFAULT_CODE_PATTERN)
        priority_keys = {
            "verification_code", "verificationcode", "verify_code", "verifycode",
            "mail_code", "mailcode", "otp", "one_time_code", "code",
        }
        ignored_keys = {
            "email", "mail", "url", "api_url", "password", "pass", "token",
            "status", "status_code", "timestamp", "created_at", "updated_at",
        }

        def walk(value: object, parent_key: str = "") -> str:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = str(key or "").strip().lower().replace("-", "_")
                    if normalized in priority_keys:
                        code = cls._match_code(child, pattern)
                        if code:
                            return code
                for key, child in value.items():
                    normalized = str(key or "").strip().lower().replace("-", "_")
                    if normalized in ignored_keys:
                        continue
                    code = walk(child, normalized)
                    if code:
                        return code
                return ""
            if isinstance(value, (list, tuple)):
                for child in value:
                    code = walk(child, parent_key)
                    if code:
                        return code
                return ""
            if isinstance(value, str) and parent_key not in ignored_keys:
                return cls._match_code(value, pattern)
            return ""

        code = walk(payload)
        if code:
            return code

        text = str(raw or "").strip()
        if not text:
            return ""
        if code_pattern:
            return cls._match_code(text, pattern)

        exact = re.fullmatch(r"[\s\"']*(\d{6})[\s\"']*", text)
        if exact:
            return exact.group(1)
        labelled = re.search(
            r"(?:验证码|校验码|动态码|verification\s*code|one[- ]?time\s*code|otp|code)"
            r"[^0-9]{0,20}(\d{6})(?!\d)",
            text,
            flags=re.IGNORECASE,
        )
        if labelled:
            return labelled.group(1)

        safe_text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", " ", text, flags=re.IGNORECASE)
        safe_text = re.sub(r"https?://\S+", " ", safe_text, flags=re.IGNORECASE)
        candidates = list(dict.fromkeys(re.findall(DEFAULT_CODE_PATTERN, safe_text)))
        return candidates[0] if len(candidates) == 1 else ""

    @classmethod
    def _signatures(cls, payload: object | None, raw: str) -> set[str]:
        signatures: set[str] = set()
        code = cls._extract_code(payload, raw)
        if code:
            signatures.add(f"code:{code}")
        link = _extract_verification_link(raw, "")
        if link:
            signatures.add("link:" + hashlib.sha256(link.encode("utf-8")).hexdigest())
        normalized = raw
        if payload is not None:
            try:
                normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            except Exception:
                pass
        if normalized:
            signatures.add("body:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest())
        return signatures

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            payload, raw = self._request(self._entry_for_account(account))
            return self._signatures(payload, raw)
        except Exception:
            return set()

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set | None = None,
        code_pattern: str | None = None,
    ) -> str:
        del keyword  # This API exposes the requested mailbox's code directly.
        entry = self._entry_for_account(account)
        seen = set(before_ids or set())
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                payload, raw = self._request(entry)
                code = self._extract_code(payload, raw, code_pattern=code_pattern)
                signatures = self._signatures(payload, raw)
                code_signature = f"code:{code}" if code else ""
                if code and code_signature not in seen:
                    return code
                seen.update(signatures)
            except Exception as exc:
                last_error = str(exc).strip() or exc.__class__.__name__
            time.sleep(self.poll_interval)
        suffix = f"，最后错误: {last_error}" if last_error else ""
        raise TimeoutError(f"等待 API 邮箱验证码超时 ({timeout}s){suffix}")

    def wait_for_link(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set | None = None,
    ) -> str:
        entry = self._entry_for_account(account)
        seen = set(before_ids or set())
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                payload, raw = self._request(entry)
                link = _extract_verification_link(raw, keyword)
                link_signature = "link:" + hashlib.sha256(link.encode("utf-8")).hexdigest() if link else ""
                if link and link_signature not in seen:
                    return link
                seen.update(self._signatures(payload, raw))
            except Exception as exc:
                last_error = str(exc).strip() or exc.__class__.__name__
            time.sleep(self.poll_interval)
        suffix = f"，最后错误: {last_error}" if last_error else ""
        raise TimeoutError(f"等待 API 邮箱验证链接超时 ({timeout}s){suffix}")
