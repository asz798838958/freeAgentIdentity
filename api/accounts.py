from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from application.account_exports import AccountExportsService, ExportArtifact
from application.accounts import AccountsService
from domain.accounts import AccountExportSelection, AccountQuery, AccountUpdateCommand

router = APIRouter(prefix="/accounts", tags=["accounts"])
service = AccountsService()
exports_service = AccountExportsService()


class AccountUpdateRequest(BaseModel):
    password: Optional[str] = None
    user_id: Optional[str] = None
    lifecycle_status: Optional[str] = None
    overview: Optional[dict] = None
    credentials: Optional[dict] = None
    provider_accounts: Optional[list[dict]] = None
    provider_resources: Optional[list[dict]] = None
    replace_provider_accounts: bool = False
    replace_provider_resources: bool = False
    primary_token: Optional[str] = None
    cashier_url: Optional[str] = None
    region: Optional[str] = None
    trial_end_time: Optional[int] = None


class ImportRequest(BaseModel):
    platform: str
    lines: list[str]


class BatchExportRequest(BaseModel):
    platform: str = "chatgpt"
    ids: list[int] = Field(default_factory=list)
    select_all: bool = False
    status_filter: Optional[str] = None
    email_service_filter: Optional[str] = None
    search_filter: Optional[str] = None


def _stream_artifact(artifact: ExportArtifact) -> StreamingResponse:
    if isinstance(artifact.content, io.BytesIO):
        body = artifact.content
    elif isinstance(artifact.content, bytes):
        body = iter([artifact.content])
    else:
        body = iter([artifact.content])
    return StreamingResponse(
        body,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f"attachment; filename={artifact.filename}"},
    )


@router.get("")
def list_accounts(
    platform: str = "",
    status: str = "",
    email: str = "",
    page: int = 1,
    page_size: int = 20,
):
    return service.list_accounts(AccountQuery(platform=platform, status=status, email=email, page=page, page_size=page_size))


@router.get("/stats")
def get_stats():
    return service.get_stats()


@router.post("/export/json")
def export_accounts_json(body: BatchExportRequest):
    try:
        artifact = exports_service.export_chatgpt_json(
            AccountExportSelection(
                platform=body.platform,
                ids=body.ids,
                select_all=body.select_all,
                status_filter=body.status_filter or "",
                search_filter=body.search_filter or "",
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _stream_artifact(artifact)


@router.post("/export/csv")
def export_accounts_csv(body: BatchExportRequest):
    try:
        artifact = exports_service.export_chatgpt_csv(
            AccountExportSelection(
                platform=body.platform,
                ids=body.ids,
                select_all=body.select_all,
                status_filter=body.status_filter or "",
                search_filter=body.search_filter or "",
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _stream_artifact(artifact)


@router.post("/export/sub2api")
def export_accounts_sub2api(body: BatchExportRequest):
    try:
        artifact = exports_service.export_chatgpt_sub2api(
            AccountExportSelection(
                platform=body.platform,
                ids=body.ids,
                select_all=body.select_all,
                status_filter=body.status_filter or "",
                search_filter=body.search_filter or "",
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _stream_artifact(artifact)


@router.post("/export/sub2api-agent-identity")
def export_accounts_sub2api_agent_identity(body: BatchExportRequest):
    try:
        artifact = exports_service.export_chatgpt_agent_identity_sub2api(
            AccountExportSelection(
                platform=body.platform,
                ids=body.ids,
                select_all=body.select_all,
                status_filter=body.status_filter or "",
                search_filter=body.search_filter or "",
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _stream_artifact(artifact)


@router.post("/export/cpa")
def export_accounts_cpa(body: BatchExportRequest):
    try:
        artifact = exports_service.export_chatgpt_cpa(
            AccountExportSelection(
                platform=body.platform,
                ids=body.ids,
                select_all=body.select_all,
                status_filter=body.status_filter or "",
                search_filter=body.search_filter or "",
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _stream_artifact(artifact)


@router.post("/export/any2api")
def export_accounts_any2api(body: BatchExportRequest):
    try:
        artifact = exports_service.export_any2api(
            AccountExportSelection(
                platform=body.platform,
                ids=body.ids,
                select_all=body.select_all,
                status_filter=body.status_filter or "",
                search_filter=body.search_filter or "",
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _stream_artifact(artifact)


@router.post("/import")
def import_accounts(body: ImportRequest):
    return service.import_accounts(body.platform, body.lines)


@router.get("/{account_id}")
def get_account(account_id: int):
    item = service.get_account(account_id)
    if not item:
        raise HTTPException(404, "账号不存在")
    return item


@router.patch("/{account_id}")
def update_account(account_id: int, body: AccountUpdateRequest):
    item = service.update_account(account_id, AccountUpdateCommand(**body.model_dump()))
    if not item:
        raise HTTPException(404, "账号不存在")
    return item


@router.delete("/{account_id}")
def delete_account(account_id: int):
    result = service.delete_account(account_id)
    if not result["ok"]:
        raise HTTPException(404, "账号不存在")
    return result
