from __future__ import annotations

from fastapi import APIRouter, HTTPException

from application.tasks_query import TasksQueryService

router = APIRouter(prefix="/tasks", tags=["tasks"])
service = TasksQueryService()


@router.get("/{task_id}")
def get_task(task_id: str):
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{task_id}/events")
def list_task_events(task_id: str, since: int = 0, limit: int = 200):
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return service.list_events(task_id, since=since, limit=limit)
