from __future__ import annotations

from fastapi import APIRouter, HTTPException

from application.provider_definitions import ProviderDefinitionsService

router = APIRouter(prefix="/provider-definitions", tags=["provider-definitions"])
service = ProviderDefinitionsService()


@router.delete("/{definition_id}")
def delete_provider_definition(definition_id: int):
    try:
        result = service.delete_definition(definition_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not result["ok"]:
        raise HTTPException(404, "provider definition 不存在")
    return result
