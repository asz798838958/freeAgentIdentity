from __future__ import annotations

from core.datetime_utils import serialize_datetime
from infrastructure.tasks_read_repository import TasksReadRepository


class TasksQueryService:
    def __init__(self, repository: TasksReadRepository | None = None):
        self.repository = repository or TasksReadRepository()

    def get_task(self, task_id: str) -> dict | None:
        item = self.repository.get(task_id)
        if not item:
            return None
        return self._serialize(item)

    def list_events(self, task_id: str, *, since: int = 0, limit: int = 200) -> dict:
        items = self.repository.list_events(task_id, since=since, limit=limit)
        return {
            "items": [
                {
                    "id": item.id,
                    "task_id": item.task_id,
                    "type": item.type,
                    "level": item.level,
                    "message": item.message,
                    "line": item.line,
                    "detail": item.detail,
                    "created_at": serialize_datetime(item.created_at),
                }
                for item in items
            ]
        }

    @staticmethod
    def _serialize(item) -> dict:
        return {
            "id": item.id,
            "task_id": item.id,
            "type": item.type,
            "platform": item.platform,
            "status": item.status,
            "progress": item.progress.label,
            "progress_detail": {
                "current": item.progress.current,
                "total": item.progress.total,
                "label": item.progress.label,
            },
            "success": item.success,
            "error_count": item.error_count,
            "errors": item.errors,
            "cashier_urls": item.cashier_urls,
            "error": item.error,
            "created_at": serialize_datetime(item.created_at),
            "started_at": serialize_datetime(item.started_at),
            "finished_at": serialize_datetime(item.finished_at),
            "updated_at": serialize_datetime(item.updated_at),
            "result": item.result,
        }
