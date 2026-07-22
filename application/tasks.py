"""Task orchestration and persistence helpers."""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlmodel import Session, select

from core.account_graph import (
    load_account_graphs,
    patch_account_graph,
    recover_lifecycle_status_for_valid_account,
)
from core.base_platform import AccountStatus, RegisterConfig
from core.datetime_utils import format_local_clock, serialize_datetime
from core.db import AccountModel, TaskEventModel, TaskModel, engine, save_account
from core.platform_accounts import build_platform_account
from core.registry import get
from infrastructure.platform_runtime import PlatformRuntime

TASK_TYPE_REGISTER = "register"
TASK_TYPE_ACCOUNT_CHECK_ALL = "account_check_all"
TASK_TYPE_PLATFORM_ACTION = "platform_action"

TASK_STATUS_PENDING = "pending"
TASK_STATUS_CLAIMED = "claimed"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_INTERRUPTED = "interrupted"
TASK_STATUS_CANCEL_REQUESTED = "cancel_requested"
TASK_STATUS_CANCELLED = "cancelled"

TERMINAL_TASK_STATUSES = {
    TASK_STATUS_SUCCEEDED,
    TASK_STATUS_FAILED,
    TASK_STATUS_INTERRUPTED,
    TASK_STATUS_CANCELLED,
}
ACTIVE_TASK_STATUSES = {
    TASK_STATUS_CLAIMED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_CANCEL_REQUESTED,
}

_task_locks: dict[str, threading.Lock] = {}
_task_locks_guard = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat().replace("+00:00", "Z")


def _serialize_datetime(value: datetime | None) -> str | None:
    return serialize_datetime(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return _serialize_datetime(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _dump_json(data: Any) -> str:
    return json.dumps(data or {}, ensure_ascii=False, default=_json_default)


def _task_lock(task_id: str) -> threading.Lock:
    with _task_locks_guard:
        lock = _task_locks.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _task_locks[task_id] = lock
        return lock


def _mutate_task(task_id: str, fn: Callable[[TaskModel], None]) -> Optional[TaskModel]:
    with _task_lock(task_id):
        with Session(engine) as session:
            task = session.get(TaskModel, task_id)
            if not task:
                return None
            fn(task)
            task.updated_at = _utcnow()
            session.add(task)
            session.commit()
            session.refresh(task)
            return task


def _task_result_seed(result: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {"errors": [], "cashier_urls": [], "data": None}
    if result:
        base.update(result)
    return base


def _task_account_keys(task_type: str, payload: dict[str, Any]) -> list[str]:
    if task_type == TASK_TYPE_PLATFORM_ACTION:
        account_id = int(payload.get("account_id", 0) or 0)
        if account_id > 0:
            return [f"account:{account_id}"]
    return []


def serialize_task(task: TaskModel) -> dict[str, Any]:
    result = task.get_result()
    progress_total = int(task.progress_total or 0)
    progress_current = int(task.progress_current or 0)
    return {
        "id": task.id,
        "task_id": task.id,
        "type": task.type,
        "platform": task.platform,
        "status": task.status,
        "terminal": task.status in TERMINAL_TASK_STATUSES,
        "cancellable": task.status in {TASK_STATUS_PENDING, TASK_STATUS_CLAIMED, TASK_STATUS_RUNNING, TASK_STATUS_CANCEL_REQUESTED},
        "progress": f"{progress_current}/{progress_total}" if progress_total else "0/0",
        "progress_detail": {
            "current": progress_current,
            "total": progress_total,
            "label": f"{progress_current}/{progress_total}" if progress_total else "0/0",
        },
        "success": int(task.success_count or 0),
        "error_count": int(task.error_count or 0),
        "errors": list(result.get("errors", [])),
        "cashier_urls": list(result.get("cashier_urls", [])),
        "data": result.get("data"),
        "result": result,
        "error": task.error,
        "created_at": _serialize_datetime(task.created_at),
        "started_at": _serialize_datetime(task.started_at),
        "finished_at": _serialize_datetime(task.finished_at),
        "updated_at": _serialize_datetime(task.updated_at),
    }


def serialize_event(event: TaskEventModel) -> dict[str, Any]:
    return {
        "id": event.id,
        "task_id": event.task_id,
        "type": event.type,
        "level": event.level,
        "message": event.message,
        "line": f"[{format_local_clock(event.created_at)}] {event.message}",
        "detail": event.get_detail(),
        "created_at": _serialize_datetime(event.created_at),
    }


def create_task(
    *,
    task_type: str,
    platform: str,
    payload: dict[str, Any],
    progress_total: int = 1,
    result_seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = f"task_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    task = TaskModel(
        id=task_id,
        type=task_type,
        platform=platform,
        status=TASK_STATUS_PENDING,
        payload_json=_dump_json(payload),
        result_json=_dump_json(_task_result_seed(result_seed)),
        progress_current=0,
        progress_total=max(int(progress_total or 0), 0),
    )
    with Session(engine) as session:
        session.add(task)
        session.commit()
        session.refresh(task)
    append_task_event(task.id, f"任务已创建: {task_type}", event_type="state")
    return serialize_task(task)


def create_register_task(payload: dict[str, Any]) -> dict[str, Any]:
    count = max(int(payload.get("count", 1) or 1), 1)
    payload = {**payload, "platform": "chatgpt"}
    return create_task(
        task_type=TASK_TYPE_REGISTER,
        platform="chatgpt",
        payload=payload,
        progress_total=count,
    )


def create_account_check_all_task(platform: str = "", limit: int = 50) -> dict[str, Any]:
    return create_task(
        task_type=TASK_TYPE_ACCOUNT_CHECK_ALL,
        platform=platform,
        payload={"platform": platform, "limit": int(limit or 50)},
        progress_total=max(int(limit or 50), 1),
    )


def create_platform_action_task(payload: dict[str, Any]) -> dict[str, Any]:
    return create_task(
        task_type=TASK_TYPE_PLATFORM_ACTION,
        platform=str(payload.get("platform", "")),
        payload=payload,
        progress_total=1,
    )


def get_task(task_id: str) -> Optional[dict[str, Any]]:
    with Session(engine) as session:
        task = session.get(TaskModel, task_id)
        return serialize_task(task) if task else None


def list_task_events(task_id: str, *, since: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 500)
    with Session(engine) as session:
        q = (
            select(TaskEventModel)
            .where(TaskEventModel.task_id == task_id)
            .where(TaskEventModel.id > since)
            .order_by(TaskEventModel.id)
            .limit(limit)
        )
        items = session.exec(q).all()
    return [serialize_event(item) for item in items]


def append_task_event(task_id: str, message: str, *, event_type: str = "log", level: str = "info", detail: dict | None = None) -> dict[str, Any]:
    with Session(engine) as session:
        event = TaskEventModel(
            task_id=task_id,
            type=event_type,
            level=level,
            message=message,
            detail_json=_dump_json(detail or {}),
        )
        session.add(event)
        session.commit()
        session.refresh(event)
    return serialize_event(event)


def mark_incomplete_tasks_interrupted() -> None:
    interrupted_ids: list[str] = []
    with Session(engine) as session:
        non_terminal = [TASK_STATUS_PENDING] + list(ACTIVE_TASK_STATUSES)
        tasks = session.exec(
            select(TaskModel).where(TaskModel.status.in_(non_terminal))
        ).all()
        for task in tasks:
            task.status = TASK_STATUS_INTERRUPTED
            task.error = task.error or "任务在服务重启后被中断"
            task.finished_at = _utcnow()
            task.updated_at = _utcnow()
            session.add(task)
            interrupted_ids.append(task.id)
        session.commit()
    for task_id in interrupted_ids:
        append_task_event(
            task_id,
            "任务在服务重启后被标记为中断",
            event_type="state",
            level="warning",
        )


def request_cancel(task_id: str) -> Optional[dict[str, Any]]:
    task = _mutate_task(
        task_id,
        lambda model: _request_cancel_mutation(model),
    )
    if not task:
        return None
    append_task_event(task_id, "已请求取消任务", event_type="state", level="warning")
    return serialize_task(task)


def _request_cancel_mutation(task: TaskModel) -> None:
    if task.status in TERMINAL_TASK_STATUSES:
        return
    if task.status == TASK_STATUS_PENDING:
        task.status = TASK_STATUS_CANCELLED
        task.finished_at = _utcnow()
        task.error = task.error or "任务在开始前被取消"
    else:
        task.status = TASK_STATUS_CANCEL_REQUESTED


def claim_next_runnable_task(
    *,
    running_platform_counts: dict[str, int] | None = None,
    busy_account_keys: set[str] | None = None,
    max_parallel_per_platform: int = 1,
) -> Optional[dict[str, Any]]:
    running_platform_counts = dict(running_platform_counts or {})
    busy_account_keys = set(busy_account_keys or set())
    with Session(engine) as session:
        tasks = session.exec(
            select(TaskModel)
            .where(TaskModel.status == TASK_STATUS_PENDING)
            .order_by(TaskModel.created_at)
        ).all()
        for task in tasks:
            payload = task.get_payload()
            platform = task.platform or str(payload.get("platform", "") or "")
            account_keys = _task_account_keys(task.type, payload)
            if platform and running_platform_counts.get(platform, 0) >= max_parallel_per_platform:
                continue
            if account_keys and busy_account_keys.intersection(account_keys):
                continue
            task.status = TASK_STATUS_CLAIMED
            task.started_at = task.started_at or _utcnow()
            task.updated_at = _utcnow()
            session.add(task)
            session.commit()
            return {"id": task.id, "platform": platform, "account_keys": account_keys}
    return None


class TaskLogger:
    def __init__(self, task_id: str):
        self.task_id = task_id
        # 并发任务里每个 worker 通过 ``set_subtask`` 把自己的 subtask_id
        # 绑到 thread-local，之后 ``log()`` 自动把 ``subtask_id`` 注入
        # 事件 detail，前端按这个分组折叠展示。
        self._tlocal = threading.local()

    def set_subtask(self, subtask_id: str, label: str = "") -> None:
        """绑定当前线程的子任务标签。子任务结束后调 ``clear_subtask`` 解绑。

        ``subtask_id`` 是稳定标识（如 ``worker_1``）；``label`` 是给前端
        展示的人类可读标题（如"账号 #1"）。
        """
        self._tlocal.subtask_id = str(subtask_id or "")
        self._tlocal.subtask_label = str(label or "")

    def clear_subtask(self) -> None:
        try:
            del self._tlocal.subtask_id
        except AttributeError:
            pass
        try:
            del self._tlocal.subtask_label
        except AttributeError:
            pass

    def _current_subtask(self) -> tuple[str, str]:
        sid = getattr(self._tlocal, "subtask_id", "") or ""
        label = getattr(self._tlocal, "subtask_label", "") or ""
        return sid, label

    def log(self, message: str, *, level: str = "info", event_type: str = "log", detail: dict | None = None) -> None:
        # 自动给当前线程绑定的 subtask 加 detail，用于前端按 worker 分组折叠
        merged_detail = dict(detail or {})
        sid, slabel = self._current_subtask()
        if sid and "subtask_id" not in merged_detail:
            merged_detail["subtask_id"] = sid
        if slabel and "subtask_label" not in merged_detail:
            merged_detail["subtask_label"] = slabel
        append_task_event(
            self.task_id,
            message,
            event_type=event_type,
            level=level,
            detail=merged_detail or None,
        )
        prefix = f"[task:{self.task_id}]"
        if sid:
            prefix += f"[{sid}]"
        print(f"{prefix} {message}")

    def mark_running(self) -> None:
        def _update(task: TaskModel) -> None:
            task.status = TASK_STATUS_RUNNING
            task.started_at = task.started_at or _utcnow()

        _mutate_task(self.task_id, _update)
        self.log("任务已开始执行", event_type="state")

    def is_cancel_requested(self) -> bool:
        with Session(engine) as session:
            task = session.get(TaskModel, self.task_id)
            return bool(task and task.status == TASK_STATUS_CANCEL_REQUESTED)

    def set_progress(self, current: int, total: Optional[int] = None) -> None:
        current = max(int(current), 0)

        def _update(task: TaskModel) -> None:
            task.progress_current = current
            if total is not None:
                task.progress_total = max(int(total), 0)

        _mutate_task(self.task_id, _update)

    def record_success(self) -> None:
        def _update(task: TaskModel) -> None:
            task.success_count += 1

        _mutate_task(self.task_id, _update)

    def record_error(self, error: str) -> None:
        def _update(task: TaskModel) -> None:
            task.error_count += 1
            result = task.get_result()
            errors = list(result.get("errors", []))
            errors.append(error)
            result["errors"] = errors
            task.set_result(result)

        _mutate_task(self.task_id, _update)

    def add_cashier_url(self, url: str) -> None:
        def _update(task: TaskModel) -> None:
            result = task.get_result()
            urls = list(result.get("cashier_urls", []))
            urls.append(url)
            result["cashier_urls"] = urls
            task.set_result(result)

        _mutate_task(self.task_id, _update)

    def set_result_data(self, data: Any) -> None:
        def _update(task: TaskModel) -> None:
            result = task.get_result()
            result["data"] = data
            task.set_result(result)

        _mutate_task(self.task_id, _update)

    def finish(self, status: str, *, error: str = "") -> None:
        def _update(task: TaskModel) -> None:
            task.status = status
            task.finished_at = _utcnow()
            if error:
                task.error = error

        _mutate_task(self.task_id, _update)
        event_level = "error" if status == TASK_STATUS_FAILED else ("warning" if status in {TASK_STATUS_INTERRUPTED, TASK_STATUS_CANCELLED} else "info")
        self.log(
            f"任务结束: {status}",
            level=event_level,
            event_type="state",
            detail={"status": status, "error": error},
        )


def _build_platform_instance(platform_name: str, payload: dict[str, Any], logger: TaskLogger, resolved_proxy: str | None = None, shared_mailbox=None):
    from core.base_identity import normalize_identity_provider
    from core.base_mailbox import create_mailbox

    executor_type = str(payload.get("executor_type", "headless") or "headless")
    captcha_solver = str(payload.get("captcha_solver", "auto") or "auto")
    extra = dict(payload.get("extra") or {})
    config = RegisterConfig(
        executor_type=executor_type,
        captcha_solver=captcha_solver,
        proxy=resolved_proxy,
        extra=extra,
    )
    identity_provider = normalize_identity_provider(extra.get("identity_provider", "mailbox"))
    mailbox = shared_mailbox
    if mailbox is None and identity_provider == "mailbox":
        if not extra.get("mail_provider"):
            from infrastructure.provider_settings_repository import ProviderSettingsRepository

            extra["mail_provider"] = ProviderSettingsRepository().get_default_provider_key("mailbox")
        mailbox = create_mailbox(
            provider=extra.get("mail_provider", ""),
            extra=extra,
            proxy=resolved_proxy,
        )

    platform_cls = get(platform_name)
    platform = platform_cls(config=config, mailbox=mailbox)
    if hasattr(platform, "set_logger"):
        platform.set_logger(logger.log)
    else:
        platform._log_fn = logger.log
    return platform


def _run_single_account_check(account_id: int, logger: TaskLogger | None = None) -> tuple[bool, dict[str, Any]]:
    with Session(engine) as session:
        model = session.get(AccountModel, account_id)
        if not model:
            raise ValueError("账号不存在")
        plugin = get(model.platform)(config=RegisterConfig())
        account = build_platform_account(session, model)

    valid = plugin.check_valid(account)
    with Session(engine) as session:
        model = session.get(AccountModel, account_id)
        if model:
            model.updated_at = _utcnow()
            current_graph = load_account_graphs(session, [account_id]).get(account_id, {})
            summary_updates = {"checked_at": _utcnow_iso(), "valid": bool(valid)}
            if hasattr(plugin, "get_last_check_overview"):
                summary_updates.update(plugin.get_last_check_overview() or {})
            lifecycle_status = None
            if valid:
                # **bug 修复**：原实现 ``recover_lifecycle_status_for_valid_account``
                # 直接读 ``current_graph`` 老快照——但 plugin 刚拉到的新
                # ``plan_state`` 在 ``summary_updates`` 里、还没写回 graph，
                # 导致 free → 重新刷新仍然被认成 subscribed。这里把
                # ``summary_updates`` merge 到 graph 里再算 lifecycle。
                merged_graph = dict(current_graph)
                merged_overview = dict(merged_graph.get("overview") or {})
                merged_overview.update(summary_updates)
                merged_graph["overview"] = merged_overview
                lifecycle_status = recover_lifecycle_status_for_valid_account(merged_graph)
            patch_account_graph(
                session,
                model,
                lifecycle_status=lifecycle_status,
                summary_updates=summary_updates,
            )
            session.add(model)
            session.commit()

    result = {"account_id": account_id, "valid": bool(valid), "platform": account.platform, "email": account.email}
    if logger:
        logger.log(f"{account.email}: {'有效' if valid else '失效'}")
    return valid, result


def execute_task(task_id: str) -> None:
    with Session(engine) as session:
        task = session.get(TaskModel, task_id)
        if not task:
            return
        task_type = task.type
        payload = task.get_payload()

    logger = TaskLogger(task_id)
    logger.mark_running()

    if logger.is_cancel_requested():
        logger.finish(TASK_STATUS_CANCELLED, error="任务在启动后立即被取消")
        return

    handlers: dict[str, Callable[[dict[str, Any], TaskLogger], None]] = {
        TASK_TYPE_REGISTER: _execute_register_task,
        TASK_TYPE_ACCOUNT_CHECK_ALL: _execute_account_check_all_task,
        TASK_TYPE_PLATFORM_ACTION: _execute_platform_action_task,
    }
    handler = handlers.get(task_type)
    if not handler:
        logger.finish(TASK_STATUS_FAILED, error=f"未知任务类型: {task_type}")
        return
    handler(payload, logger)


def _resolve_registration_proxy_for_platform(
    platform_name: str,
    *,
    explicit_proxy: str | None,
    proxy_getter: Callable[[], str | None],
) -> str | None:
    normalized_explicit_proxy = str(explicit_proxy or "").strip() or None
    if str(platform_name or "").strip().lower() == "chatgpt":
        # ChatGPT 只使用本次任务显式传入的动态 IP；留空时固定本地直连，
        # 不从全局代理池回退。
        return normalized_explicit_proxy
    return normalized_explicit_proxy or proxy_getter()


def _execute_register_task(payload: dict[str, Any], logger: TaskLogger) -> None:
    from core.proxy_pool import proxy_pool

    count = max(int(payload.get("count", 1) or 1), 1)
    concurrency = min(max(int(payload.get("concurrency", 1) or 1), 1), count, 5)
    platform_name = "chatgpt"
    email = payload.get("email") or None
    password = payload.get("password") or None
    explicit_proxy = str(payload.get("proxy") or "").strip() or None
    extra = dict(payload.get("extra") or {})
    resolved_proxy = _resolve_registration_proxy_for_platform(
        platform_name,
        explicit_proxy=explicit_proxy,
        proxy_getter=proxy_pool.get_next,
    )

    logger.set_progress(0, count)
    try:
        get(platform_name)
    except Exception as exc:
        logger.log(f"致命错误: {exc}", level="error")
        logger.finish(TASK_STATUS_FAILED, error=str(exc))
        return

    shared_mailbox = None
    try:
        from core.base_identity import normalize_identity_provider
        from core.base_mailbox import create_mailbox

        identity_provider = normalize_identity_provider(extra.get("identity_provider", "mailbox"))
        if identity_provider == "mailbox":
            if not extra.get("mail_provider"):
                from infrastructure.provider_settings_repository import ProviderSettingsRepository

                extra["mail_provider"] = ProviderSettingsRepository().get_default_provider_key("mailbox")
            shared_mailbox = create_mailbox(
                provider=extra.get("mail_provider", ""),
                extra=extra,
                proxy=resolved_proxy,
            )
    except Exception as exc:
        logger.log(f"邮箱初始化失败: {exc}", level="error")
        logger.finish(TASK_STATUS_FAILED, error=f"邮箱初始化失败: {exc}")
        return

    def _do_one(index: int) -> dict[str, Any] | str:
        if logger.is_cancel_requested():
            return "__cancel_requested__"
        logger.set_subtask(f"worker_{index + 1}", f"Worker {index + 1}")
        try:
            platform = _build_platform_instance(
                platform_name,
                payload,
                logger,
                resolved_proxy=resolved_proxy,
                shared_mailbox=shared_mailbox,
            )
            logger.log(f"开始注册第 {index + 1}/{count} 个账号")
            if resolved_proxy:
                logger.log(f"使用代理: {resolved_proxy}")
            account = platform.register(email=email, password=password)
            saved_account = save_account(account)
            if resolved_proxy:
                proxy_pool.report_success(resolved_proxy)
            logger.record_success()
            logger.log(f"注册成功: {account.email}")
            return {
                "account_id": int(saved_account.id),
                "email": account.email,
            }
        except Exception as exc:
            if resolved_proxy:
                proxy_pool.report_fail(resolved_proxy)
            error = str(exc)
            logger.record_error(error)
            logger.log(f"注册失败: {error}", level="error")
            return error
        finally:
            logger.clear_subtask()

    success = 0
    errors: list[str] = []
    registered_accounts: list[dict[str, Any]] = []
    completed = 0
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            pending = {pool.submit(_do_one, index) for index in range(count)}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    result = future.result()
                    completed += 1
                    if isinstance(result, dict):
                        success += 1
                        registered_accounts.append(result)
                    elif result != "__cancel_requested__":
                        errors.append(str(result))
                    logger.set_progress(completed, count)
    except Exception as exc:
        logger.log(f"致命错误: {exc}", level="error")
        logger.finish(TASK_STATUS_FAILED, error=str(exc))
        return

    logger.set_result_data(
        {
            "success": success,
            "fail": len(errors),
            "account_ids": [item["account_id"] for item in registered_accounts],
            "accounts": registered_accounts,
            "auto_download_agent_identity": bool(
                extra.get("auto_download_agent_identity")
            ),
        }
    )
    logger.log(f"完成: 成功 {success} 个, 失败 {len(errors)} 个", event_type="summary")
    if logger.is_cancel_requested():
        logger.finish(TASK_STATUS_CANCELLED, error="任务已取消")
        return
    final_status = TASK_STATUS_FAILED if errors and success == 0 else TASK_STATUS_SUCCEEDED
    logger.finish(final_status, error=errors[0] if final_status == TASK_STATUS_FAILED else "")


def _execute_platform_action_task(payload: dict[str, Any], logger: TaskLogger) -> None:
    if logger.is_cancel_requested():
        logger.finish(TASK_STATUS_CANCELLED, error="任务已取消")
        return
    command_platform = str(payload.get("platform", ""))
    account_id = int(payload.get("account_id", 0) or 0)
    action_id = str(payload.get("action_id", ""))
    params = dict(payload.get("params") or {})
    runtime = PlatformRuntime()
    result = runtime.execute_action(
        type("Command", (), {
            "platform": command_platform,
            "account_id": account_id,
            "action_id": action_id,
            "params": params,
        })(),
        log_fn=logger.log,
        cancel_check=logger.is_cancel_requested,
    )
    if logger.is_cancel_requested() or str(result.error or "") == "任务已取消":
        logger.finish(TASK_STATUS_CANCELLED, error="任务已取消")
        return
    if not result.ok:
        logger.record_error(result.error)
        logger.finish(TASK_STATUS_FAILED, error=result.error)
        return
    logger.set_result_data(result.data)
    message = ""
    if isinstance(result.data, dict):
        message = str(result.data.get("message", "") or "")
    if message:
        logger.log(message, event_type="summary")
    logger.set_progress(1, 1)
    logger.finish(TASK_STATUS_SUCCEEDED)


def _execute_account_check_all_task(payload: dict[str, Any], logger: TaskLogger) -> None:
    platform = str(payload.get("platform", "") or "")
    limit = max(int(payload.get("limit", 50) or 50), 1)

    with Session(engine) as session:
        q = select(AccountModel)
        if platform:
            q = q.where(AccountModel.platform == platform)
        q = q.order_by(AccountModel.created_at.desc(), AccountModel.id.desc())
        accounts = session.exec(q.limit(limit)).all()

    total = len(accounts)
    logger.set_progress(0, total)
    if total == 0:
        logger.set_result_data({"valid": 0, "invalid": 0, "error": 0})
        logger.finish(TASK_STATUS_SUCCEEDED)
        return

    results = {"valid": 0, "invalid": 0, "error": 0}
    completed = 0
    for model in accounts:
        if logger.is_cancel_requested():
            logger.finish(TASK_STATUS_CANCELLED, error="任务已取消")
            return
        try:
            valid, _ = _run_single_account_check(int(model.id or 0), logger)
            if valid:
                results["valid"] += 1
            else:
                results["invalid"] += 1
        except Exception as exc:
            results["error"] += 1
            logger.record_error(str(exc))
            logger.log(f"{model.email}: 检测异常 {exc}", level="error")
        completed += 1
        logger.set_progress(completed, total)
    logger.set_result_data(results)
    logger.finish(TASK_STATUS_SUCCEEDED)
