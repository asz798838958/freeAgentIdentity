from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from application.actions import ActionsService
from domain.actions import ActionExecutionCommand

router = APIRouter(prefix="/actions", tags=["actions"])
service = ActionsService()


class ActionRequest(BaseModel):
    params: dict = Field(default_factory=dict)


@router.get("/chatgpt")
def list_actions():
    return service.list_actions("chatgpt")


@router.post("/chatgpt/{account_id}/{action_id}")
def execute_action(account_id: int, action_id: str, body: ActionRequest):
    task = service.execute_action(
        ActionExecutionCommand(
            platform="chatgpt",
            account_id=account_id,
            action_id=action_id,
            params=body.params,
        )
    )
    if not task:
        raise HTTPException(400, "任务创建失败")
    return task
