from __future__ import annotations

from application import tasks as tasks_module
from core.base_platform import Account
from domain.actions import ActionExecutionResult
from domain.actions import ActionExecutionCommand
from infrastructure import platform_runtime as runtime_module


class _FakeLogger:
    def __init__(self):
        self.events = []
        self.result_data = None
        self.finished = None
        self.cancel_requested = False

    def log(self, message, **kwargs):
        self.events.append(("log", message, kwargs))

    def record_error(self, error):
        self.events.append(("error", error, {}))

    def record_success(self):
        self.events.append(("success", "", {}))

    def set_result_data(self, data):
        self.result_data = data

    def set_progress(self, current, total):
        self.events.append(("progress", current, {"total": total}))

    def is_cancel_requested(self):
        return self.cancel_requested

    def set_subtask(self, subtask_id, label=""):
        self.events.append(("subtask", subtask_id, {"label": label}))

    def clear_subtask(self):
        self.events.append(("clear_subtask", "", {}))

    def finish(self, status, *, error=""):
        self.finished = (status, error)


def test_platform_action_task_passes_task_logger_to_runtime(monkeypatch):
    seen = {}

    class FakeRuntime:
        def execute_action(self, command, *, log_fn=None, cancel_check):
            seen["log_fn"] = log_fn
            seen["cancel_check"] = cancel_check
            if log_fn:
                log_fn("checkout step log")
            return ActionExecutionResult(ok=True, data={"message": "summary"})

    monkeypatch.setattr(tasks_module, "PlatformRuntime", FakeRuntime)
    logger = _FakeLogger()

    tasks_module._execute_platform_action_task(
        {
            "platform": "chatgpt",
            "account_id": 123,
            "action_id": "query_state",
            "params": {},
        },
        logger,
    )

    assert getattr(seen["log_fn"], "__self__", None) is logger
    assert getattr(seen["log_fn"], "__name__", "") == "log"
    assert getattr(seen["cancel_check"], "__self__", None) is logger
    assert getattr(seen["cancel_check"], "__name__", "") == "is_cancel_requested"
    assert seen["cancel_check"]() is False
    assert ("log", "checkout step log", {}) in logger.events
    assert logger.result_data == {"message": "summary"}
    assert logger.finished == (tasks_module.TASK_STATUS_SUCCEEDED, "")


def test_chatgpt_register_task_succeeds_after_successful_registration(monkeypatch):
    class FakePlatform:
        def register(self, email=None, password=None):
            return Account(
                platform="chatgpt",
                email=email or "registered@example.com",
                password=password or "Secret123!",
                user_id="acct_123",
                extra={"access_token": "access-token"},
            )

    monkeypatch.setattr(tasks_module, "get", lambda platform_name: object)
    monkeypatch.setattr(
        tasks_module,
        "_resolve_registration_proxy_for_platform",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        tasks_module,
        "_build_platform_instance",
        lambda *args, **kwargs: FakePlatform(),
    )
    monkeypatch.setattr(
        tasks_module,
        "save_account",
        lambda account: type("SavedAccount", (), {"id": 123})(),
    )
    monkeypatch.setattr("core.base_mailbox.create_mailbox", lambda *args, **kwargs: object())

    logger = _FakeLogger()

    tasks_module._execute_register_task(
        {
            "platform": "chatgpt",
            "count": 1,
            "concurrency": 1,
            "email": "registered@example.com",
            "password": "Secret123!",
            "extra": {
                "identity_provider": "mailbox",
                "auto_download_agent_identity": True,
            },
        },
        logger,
    )

    assert logger.finished == (tasks_module.TASK_STATUS_SUCCEEDED, "")
    assert logger.result_data == {
        "success": 1,
        "fail": 0,
        "account_ids": [123],
        "accounts": [
            {
                "account_id": 123,
                "email": "registered@example.com",
            }
        ],
        "auto_download_agent_identity": True,
    }
    assert any(event[0] == "success" for event in logger.events)
    assert not any(
        "cannot access local variable 'extra'" in str(event)
        for event in logger.events
    )


def test_register_api_preserves_protocol_outlook_pool(client, monkeypatch):
    captured = {}

    def fake_create(payload):
        captured.update(payload)
        return {"task_id": "task_protocol"}

    monkeypatch.setattr("api.task_commands.command_service.create_register_task", fake_create)
    pool_text = "user@outlook.com----mail-pass----client-id----refresh-token"

    response = client.post(
        "/api/tasks/register",
        json={
            "count": 1,
            "concurrency": 1,
            "executor_type": "protocol",
            "extra": {
                "local_ms_pool_text": pool_text,
                "auto_download_agent_identity": True,
            },
        },
    )

    assert response.status_code == 200
    assert captured["executor_type"] == "protocol"
    assert captured["extra"]["mail_provider"] == "local_ms_pool"
    assert captured["extra"]["local_ms_pool_text"] == pool_text
    assert captured["extra"]["auto_download_agent_identity"] is True


def test_register_api_rejects_protocol_without_outlook_pool(client):
    response = client.post(
        "/api/tasks/register",
        json={"executor_type": "protocol", "count": 1, "extra": {}},
    )

    assert response.status_code == 400
    assert "Outlook" in response.json()["detail"]


def test_platform_action_task_finishes_cancelled_without_starting_runtime(monkeypatch):
    class FakeRuntime:
        def execute_action(self, *args, **kwargs):
            raise AssertionError("runtime should not start after cancellation")

    monkeypatch.setattr(tasks_module, "PlatformRuntime", FakeRuntime)
    logger = _FakeLogger()
    logger.cancel_requested = True

    tasks_module._execute_platform_action_task(
        {
            "platform": "chatgpt",
            "account_id": 123,
            "action_id": "query_state",
            "params": {},
        },
        logger,
    )

    assert logger.finished == (tasks_module.TASK_STATUS_CANCELLED, "任务已取消")


def test_platform_action_task_marks_cancelled_after_runtime_cancel(monkeypatch):
    class FakeRuntime:
        def execute_action(self, command, *, log_fn=None, cancel_check):
            assert cancel_check() is False
            logger.cancel_requested = True
            return ActionExecutionResult(ok=False, error="任务已取消")

    monkeypatch.setattr(tasks_module, "PlatformRuntime", FakeRuntime)
    logger = _FakeLogger()

    tasks_module._execute_platform_action_task(
        {
            "platform": "chatgpt",
            "account_id": 123,
            "action_id": "query_state",
            "params": {},
        },
        logger,
    )

    assert logger.finished == (tasks_module.TASK_STATUS_CANCELLED, "任务已取消")


def test_platform_runtime_wires_log_fn_to_platform(monkeypatch):
    logs = []
    seen = {}

    class FakeSession:
        def __init__(self, engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, model_cls, account_id):
            return type("Model", (), {"id": account_id, "platform": "chatgpt"})()

        def add(self, model):
            pass

        def commit(self):
            pass

    class FakePlatform:
        def __init__(self, config=None):
            self._log_fn = print

        def set_logger(self, logger):
            self._log_fn = logger

        def set_cancel_checker(self, checker):
            seen["cancel_check"] = checker

        def execute_action(self, action_id, account, params):
            self._log_fn("runtime platform log")
            assert self.is_cancel_requested() is False
            return {"ok": True, "data": {"message": "ok"}}

        def is_cancel_requested(self):
            return seen["cancel_check"]()

    monkeypatch.setattr(runtime_module, "Session", FakeSession)
    monkeypatch.setattr(runtime_module, "load_all", lambda: None)
    monkeypatch.setattr(runtime_module, "get", lambda platform: FakePlatform)
    monkeypatch.setattr(runtime_module, "build_platform_account", lambda session, model: object())
    monkeypatch.setattr(runtime_module, "patch_account_graph", lambda *args, **kwargs: None)

    result = runtime_module.PlatformRuntime().execute_action(
        ActionExecutionCommand(
            platform="chatgpt",
            account_id=123,
            action_id="query_state",
            params={},
        ),
        log_fn=logs.append,
        cancel_check=lambda: False,
    )

    assert result.ok is True
    assert logs == ["runtime platform log"]
    assert seen["cancel_check"]() is False
