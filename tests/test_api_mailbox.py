from __future__ import annotations

import json

from core.api_mailbox import ApiMailboxPool, parse_api_mailbox_rows


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        if isinstance(self.payload, str):
            raise ValueError("not json")
        return self.payload

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]
        return FakeResponse(payload)


def test_parse_api_mailbox_rows_accepts_email_and_full_api_url():
    rows = parse_api_mailbox_rows(
        "user+tag@outlook.com----https://mail.example/api/code?email=user%2Btag%40outlook.com&pass=secret&json=1"
    )

    assert len(rows) == 1
    assert rows[0].email == "user+tag@outlook.com"
    assert rows[0].api_url.endswith("&json=1")


def test_api_mailbox_rejects_invalid_row_format():
    try:
        parse_api_mailbox_rows("user@example.com")
    except ValueError as exc:
        assert "邮箱----完整 API URL" in str(exc)
    else:
        raise AssertionError("invalid API mailbox row should fail")


def test_api_mailbox_ignores_baseline_code_and_returns_new_code(tmp_path):
    session = FakeSession([
        {"data": {"verification_code": "111111"}},
        {"data": {"verification_code": "111111"}},
        {"data": {"verification_code": "654321"}},
    ])
    mailbox = ApiMailboxPool(
        pool_text="user@example.com----https://mail.example/api/code?token=secret",
        state_file=str(tmp_path / "state.json"),
        poll_interval=0,
        session=session,
    )
    account = mailbox.get_email()
    before_ids = mailbox.get_current_ids(account)

    code = mailbox.wait_for_code(account, timeout=1, before_ids=before_ids)

    assert code == "654321"
    assert session.calls[0][0] == "https://mail.example/api/code?token=secret"


def test_api_mailbox_extracts_labelled_plain_text_without_using_email_digits(tmp_path):
    session = FakeSession([
        "email=user927958@example.com; verification code: 482615",
    ])
    mailbox = ApiMailboxPool(
        pool_text="user927958@example.com----https://mail.example/code",
        state_file=str(tmp_path / "state.json"),
        allow_reuse=True,
        poll_interval=0,
        session=session,
    )
    account = mailbox.get_email()

    assert mailbox.wait_for_code(account, timeout=1) == "482615"


def test_api_mailbox_account_metadata_keeps_runtime_api_url(tmp_path):
    api_url = "https://mail.example/api/code?token=secret"
    mailbox = ApiMailboxPool(
        pool_text=f"user@example.com----{api_url}",
        state_file=str(tmp_path / "state.json"),
    )

    account = mailbox.get_email()

    assert account.extra["provider_account"]["provider_name"] == "api_mailbox"
    assert account.extra["provider_account"]["credentials"]["api_url"] == api_url
