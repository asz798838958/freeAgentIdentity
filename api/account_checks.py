from __future__ import annotations

from fastapi import APIRouter

from application.account_checks import AccountChecksService

router = APIRouter(prefix="/accounts", tags=["account-checks"])
service = AccountChecksService()


@router.post("/check-all")
def check_all_accounts(platform: str = "chatgpt"):
    return service.check_all_async(platform)
