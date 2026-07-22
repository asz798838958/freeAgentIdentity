from __future__ import annotations

from fastapi import APIRouter

from application.health import HealthService

router = APIRouter(tags=["health"])
service = HealthService()


@router.get("/health")
def health():
    return service.health()


@router.get("/ready")
def ready():
    return service.readiness()
