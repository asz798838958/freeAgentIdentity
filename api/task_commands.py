from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from application.task_commands import TaskCommandsService
from application.tasks_query import TasksQueryService

router = APIRouter(prefix="/tasks", tags=["task-commands"])
command_service = TaskCommandsService()
query_service = TasksQueryService()


class RegisterTaskRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    count: int = 1
    concurrency: int = 1
    proxy: Optional[str] = None
    executor_type: Literal["protocol", "headless", "headed"] = "headless"
    captcha_solver: str = "auto"
    extra: dict = Field(default_factory=dict)


@router.post("/register")
def create_register_task(body: RegisterTaskRequest):
    payload = body.model_dump()
    extra = dict(body.extra or {})
    extra["identity_provider"] = "mailbox"
    mail_provider = str(extra.get("mail_provider") or "").strip()
    if body.executor_type == "protocol":
        pool_text = str(extra.get("local_ms_pool_text") or "").strip()
        pool_file = str(extra.get("local_ms_pool_file") or "").strip()
        if not pool_text and not pool_file:
            raise HTTPException(400, "协议注册需要 Outlook 账号池文本或账号池文件")
        if pool_text:
            from core.local_ms_mailbox import parse_local_ms_pool_rows

            rows = parse_local_ms_pool_rows(pool_text)
            if not rows:
                raise HTTPException(400, "Outlook 账号池未解析到有效账号，请检查输入格式")
            allow_reuse = str(extra.get("local_ms_pool_allow_reuse") or "").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if not allow_reuse and len(rows) < body.count:
                raise HTTPException(
                    400,
                    f"Outlook 有效账号数 {len(rows)} 少于注册数量 {body.count}",
                )
        mail_provider = "local_ms_pool"
        extra["mail_provider"] = mail_provider
    payload["extra"] = extra
    if mail_provider:
        extra["mail_provider"] = mail_provider
    return command_service.create_register_task(payload)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    task = command_service.cancel_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{task_id}/logs/stream")
async def stream_logs(task_id: str, since: int = 0):
    if not query_service.get_task(task_id):
        raise HTTPException(404, "任务不存在")
    return StreamingResponse(
        command_service.stream_task_events(task_id, since=since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
