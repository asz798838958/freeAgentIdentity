from __future__ import annotations

import pytest

from core import server_guard


def test_parse_uvicorn_port_supports_separate_and_equals_forms():
    assert server_guard.parse_uvicorn_port(["uvicorn", "main:app", "--port", "8317"]) == 8317
    assert server_guard.parse_uvicorn_port(["uvicorn", "main:app", "--port=9000"]) == 9000
    assert server_guard.parse_uvicorn_port(["uvicorn", "main:app"]) == 8000


def test_duplicate_main_app_uvicorn_exits_cleanly_when_backend_is_healthy(monkeypatch):
    monkeypatch.setattr(server_guard, "is_account_manager_healthy", lambda host, port: True)
    monkeypatch.setattr(server_guard, "is_port_open", lambda host, port: True)

    should_exit, code, message = server_guard.evaluate_duplicate_start(
        ["uvicorn", "main:app", "--port", "8000"]
    )

    assert should_exit is True
    assert code == 0
    assert "already running" in message


def test_duplicate_main_app_uvicorn_fails_fast_when_port_is_occupied_by_other_service(monkeypatch):
    monkeypatch.setattr(server_guard, "is_account_manager_healthy", lambda host, port: False)
    monkeypatch.setattr(server_guard, "is_port_open", lambda host, port: True)

    should_exit, code, message = server_guard.evaluate_duplicate_start(
        ["uvicorn", "main:app", "--port", "8000"]
    )

    assert should_exit is True
    assert code == 1
    assert "already in use" in message


def test_non_uvicorn_import_does_not_exit(monkeypatch):
    monkeypatch.setattr(server_guard, "is_account_manager_healthy", lambda host, port: pytest.fail("should not probe"))
    monkeypatch.setattr(server_guard, "is_port_open", lambda host, port: pytest.fail("should not probe"))

    should_exit, code, message = server_guard.evaluate_duplicate_start(["pytest", "tests"])

    assert should_exit is False
    assert code == 0
    assert message == ""
