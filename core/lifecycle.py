"""账号生命周期管理 — 定时检测、自动续期、过期预警。"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from core.account_graph import load_account_graphs, patch_account_graph
from core.base_platform import AccountStatus, RegisterConfig
from core.db import AccountModel, AccountOverviewModel, engine
from core.platform_accounts import build_platform_account
from core.registry import get

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat().replace("+00:00", "Z")


def _utcnow_ts() -> int:
    return int(_utcnow().timestamp())


# ---------------------------------------------------------------------------
# Account validity check
# ---------------------------------------------------------------------------

def check_accounts_validity(
    *,
    platform: str = "",
    limit: int = 100,
    log_fn=None,
) -> dict[str, int]:
    """Check validity of active accounts. Returns {valid, invalid, error, skipped}."""
    log = log_fn or logger.info

    with Session(engine) as session:
        q = select(AccountModel)
        if platform:
            q = q.where(AccountModel.platform == platform)
        q = q.order_by(AccountModel.created_at.desc(), AccountModel.id.desc())
        accounts = session.exec(q.limit(limit)).all()
        graphs = load_account_graphs(session, [int(a.id) for a in accounts if a.id])

    # Only check accounts that are in an active lifecycle state
    active_statuses = {"registered", "trial", "subscribed"}
    targets = [
        a for a in accounts
        if graphs.get(int(a.id or 0), {}).get("lifecycle_status") in active_statuses
    ]

    results = {"valid": 0, "invalid": 0, "error": 0, "skipped": len(accounts) - len(targets)}
    for acc in targets:
        try:
            platform_cls = get(acc.platform)
            plugin = platform_cls(config=RegisterConfig())
            with Session(engine) as session:
                current = session.get(AccountModel, acc.id)
                if not current:
                    continue
                account_obj = build_platform_account(session, current)

            valid = plugin.check_valid(account_obj)
            with Session(engine) as session:
                model = session.get(AccountModel, acc.id)
                if model:
                    model.updated_at = _utcnow()
                    summary_updates = {"checked_at": _utcnow_iso(), "valid": valid}
                    if hasattr(plugin, "get_last_check_overview"):
                        summary_updates.update(plugin.get_last_check_overview() or {})
                    patch_account_graph(
                        session, model,
                        summary_updates=summary_updates,
                    )
                    session.add(model)
                    session.commit()
            if valid:
                results["valid"] += 1
            else:
                results["invalid"] += 1
                log(f"  {acc.email} ({acc.platform}): 失效")
        except Exception as exc:
            results["error"] += 1
            log(f"  {acc.email} ({acc.platform}): 检测异常 {exc}")

    log(f"检测完成: 有效 {results['valid']}, 失效 {results['invalid']}, "
        f"异常 {results['error']}, 跳过 {results['skipped']}")
    return results


# ---------------------------------------------------------------------------
# Token auto-refresh (ChatGPT-specific for now, extensible)
# ---------------------------------------------------------------------------

def flag_expiring_trials(
    *,
    hours_warning: int = 48,
    log_fn=None,
) -> dict[str, int]:
    """Flag trial accounts that will expire within `hours_warning` hours."""
    log = log_fn or logger.info
    now_ts = _utcnow_ts()
    warning_ts = now_ts + hours_warning * 3600
    results = {"warned": 0, "expired": 0, "skipped": 0}

    with Session(engine) as session:
        overviews = session.exec(
            select(AccountOverviewModel)
            .where(AccountOverviewModel.lifecycle_status == "trial")
        ).all()

    for overview in overviews:
        summary = overview.get_summary()
        trial_end = int(summary.get("trial_end_time") or 0)
        if not trial_end:
            results["skipped"] += 1
            continue

        if trial_end < now_ts:
            # Already expired
            with Session(engine) as session:
                model = session.get(AccountModel, overview.account_id)
                if model:
                    model.updated_at = _utcnow()
                    patch_account_graph(
                        session, model,
                        lifecycle_status=AccountStatus.EXPIRED.value,
                        summary_updates={"expiry_warning": "expired"},
                    )
                    session.add(model)
                    session.commit()
            results["expired"] += 1
        elif trial_end < warning_ts:
            # Expiring soon
            hours_left = max(0, (trial_end - now_ts) // 3600)
            with Session(engine) as session:
                model = session.get(AccountModel, overview.account_id)
                if model:
                    model.updated_at = _utcnow()
                    patch_account_graph(
                        session, model,
                        summary_updates={
                            "expiry_warning": f"expiring_in_{hours_left}h",
                            "expiry_warning_hours": hours_left,
                        },
                    )
                    session.add(model)
                    session.commit()
            results["warned"] += 1
        else:
            results["skipped"] += 1

    log(f"过期预警: 已过期 {results['expired']}, 即将过期 {results['warned']}, "
        f"跳过 {results['skipped']}")
    return results


# ---------------------------------------------------------------------------
# ChatGPT token refresh + CPA sync + liveness check
# ---------------------------------------------------------------------------

class LifecycleManager:
    """Runs periodic lifecycle tasks in a background thread."""

    def __init__(
        self,
        *,
        check_interval_hours: float = 6,
        warning_hours: int = 48,
    ):
        self.check_interval = check_interval_hours * 3600
        self.warning_hours = warning_hours
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_check = 0.0

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="lifecycle-manager")
        self._thread.start()
        print("[LifecycleManager] 已启动")

    def stop(self):
        self._running = False

    def _loop(self):
        # Wait a bit before first run to let the app fully initialize
        time.sleep(30)
        while self._running:
            now = time.time()
            try:
                # Trial expiry warnings — run every cycle
                flag_expiring_trials(hours_warning=self.warning_hours)

                # Validity check
                if now - self._last_check >= self.check_interval:
                    print("[LifecycleManager] 开始账号有效性检测...")
                    check_accounts_validity()
                    self._last_check = now

            except Exception as exc:
                print(f"[LifecycleManager] 错误: {exc}")

            # Sleep in small increments so stop() is responsive
            for _ in range(60):
                if not self._running:
                    break
                time.sleep(1)


lifecycle_manager = LifecycleManager()
