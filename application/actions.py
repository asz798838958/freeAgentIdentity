from __future__ import annotations

from domain.actions import ActionExecutionCommand
from application.tasks import create_platform_action_task
from services.task_runtime import task_runtime
from infrastructure.platform_runtime import PlatformRuntime


class ActionsService:
    def __init__(self, runtime: PlatformRuntime | None = None):
        self.runtime = runtime or PlatformRuntime()

    def list_actions(self, platform: str) -> dict:
        actions = self.runtime.list_actions(platform)
        return {
            "actions": [
                {
                    "id": action.id,
                    "label": action.label,
                    "sync": action.sync,
                    "params": [
                        {
                            "key": param.key,
                            "label": param.label,
                            "type": param.type,
                            "options": param.options,
                        }
                        for param in action.params
                    ],
                }
                for action in actions
            ]
        }
    
    def _is_sync_action(self, platform: str, action_id: str) -> bool:
        actions = self.runtime.list_actions(platform)
        return any(a.id == action_id and a.sync for a in actions)

    def execute_action(self, command: ActionExecutionCommand) -> dict:
        if self._is_sync_action(command.platform, command.action_id):
            result = self.runtime.execute_action(command)
            return {"sync": True, "ok": result.ok, "data": result.data, "error": result.error}
        task = create_platform_action_task(
            {
                "platform": command.platform,
                "account_id": command.account_id,
                "action_id": command.action_id,
                "params": command.params,
            }
        )
        task_runtime.wake_up()
        return task
