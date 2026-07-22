from __future__ import annotations

from application.tasks import create_account_check_all_task
from services.task_runtime import task_runtime


class AccountChecksService:
    def check_all_async(self, platform: str = "chatgpt") -> dict:
        task = create_account_check_all_task(platform or "chatgpt")
        task_runtime.wake_up()
        return task
