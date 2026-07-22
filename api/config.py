from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from application.config import ConfigService

router = APIRouter(prefix="/config", tags=["config"])
service = ConfigService()


class ConfigUpdateRequest(BaseModel):
    data: dict[str, str] = Field(default_factory=dict)


@router.get("")
def get_config():
    return service.get_config()


@router.get("/options")
def get_config_options():
    return service.get_options()


@router.put("")
def update_config(body: ConfigUpdateRequest):
    return service.update_config(body.data)
