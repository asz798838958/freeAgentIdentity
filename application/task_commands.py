from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from application.tasks import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_INTERRUPTED,
    TERMINAL_TASK_STATUSES,
    create_register_task,
    get_task,
    list_task_events,
    request_cancel,
)
from services.task_runtime import task_runtime


class TaskCommandsService:
    def create_register_task(self, payload: dict) -> dict:
        task = create_register_task(payload)
        task_runtime.wake_up()
        return task

    def cancel_task(self, task_id: str) -> dict | None:
        task = request_cancel(task_id)
        if task:
            task_runtime.wake_up()
        return task

    async def stream_task_events(self, task_id: str, *, since: int = 0) -> AsyncIterator[str]:
        cursor = since
        terminal_sent = False
        heartbeat_interval = 10.0
        loop = asyncio.get_running_loop()
        last_stream_activity = loop.time()

        yield "retry: 5000\n"
        yield ": connected\n\n"

        while True:
            emitted = False
            items = list_task_events(task_id, since=cursor, limit=200)
            for item in items:
                cursor = max(cursor, int(item["id"] or 0))
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                emitted = True

            current = get_task(task_id)
            if not current:
                yield f"data: {json.dumps({'done': True, 'status': TASK_STATUS_FAILED, 'line': '任务不存在'}, ensure_ascii=False)}\n\n"
                break
            if current["status"] in TERMINAL_TASK_STATUSES:
                if items:
                    await asyncio.sleep(0)
                    continue
                if not terminal_sent:
                    terminal_sent = True
                    if current["status"] == TASK_STATUS_INTERRUPTED:
                        line = "任务已中断"
                    elif current["status"] == TASK_STATUS_CANCELLED:
                        line = "任务已取消"
                    elif current["status"] == TASK_STATUS_FAILED:
                        line = current.get("error") or "任务失败"
                    else:
                        line = "任务已完成"
                    yield f"data: {json.dumps({'done': True, 'status': current['status'], 'line': line}, ensure_ascii=False)}\n\n"
                break
            if emitted:
                last_stream_activity = loop.time()
            elif loop.time() - last_stream_activity >= heartbeat_interval:
                yield ": ping\n\n"
                last_stream_activity = loop.time()
            await asyncio.sleep(0.5)
