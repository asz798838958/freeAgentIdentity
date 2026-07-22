"""
BitBrowser Profile ID 池管理。

业务诉求：用户在 BitBrowser GUI 里手工建好一批 profile（每个对应一套
独立指纹+代理），项目在跑并发 PayPal checkout 时按"轮询/取一个用一个"
的方式从这个池里挑 profile，让每个并发跑在独立的 BitBrowser profile
上，避免共用同一 profile 导致 Chromium 进程冲突或风控关联。

存储：复用现有 SQLite 的 configs 表（``core.config_store``），key 固定
为 ``bitbrowser_profile_pool``，value 是 ``\n`` 分隔的 profile_id 列表
字符串。多机部署不是项目目标场景，这种简单方案够用，且不需要新建表 +
迁移。

并发分配语义：``acquire()`` 返回当前最少被使用的 profile（in-memory
计数），``release()`` 把使用计数减回去。这样三个并发跑时一定占用三个
不同 profile（前提是池里至少 3 个）。池里数量不够时 ``acquire`` 抛
``BitBrowserProfilePoolEmpty``，调用方负责捕获并 fallback（比如继续
用环境变量 ``BIT_PROFILE_ID``）。

线程安全：所有公开方法都走同一个 ``threading.Lock``，FastAPI 的
ThreadPoolExecutor / asyncio loop 跨线程调用不会撕裂计数。
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from typing import Optional

from core.config_store import config_store


_POOL_KEY = "bitbrowser_profile_pool"


class BitBrowserProfilePoolEmpty(RuntimeError):
    """池为空 / 全部被占用时抛。"""


class BitBrowserProfilePool:
    """BitBrowser profile_id 池。

    存储是 ``configs`` 表里 ``bitbrowser_profile_pool`` 这个 key，value
    是 ``\n`` 分隔的 ID 字符串。空 ID / 重复 ID 会在持久化时被剔除。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # in-memory 当前每个 profile 的占用计数；acquire/release 维护
        self._usage: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # 持久化层
    # ------------------------------------------------------------------
    def _read_raw(self) -> list[str]:
        raw = config_store.get(_POOL_KEY, "")
        if not raw:
            return []
        # 兼容用户用 , / ; / 空格分隔的输入（虽然标准是换行）
        normalized = raw.replace(",", "\n").replace(";", "\n")
        ids: list[str] = []
        seen: set[str] = set()
        for line in normalized.splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            ids.append(cleaned)
        return ids

    def _write_raw(self, ids: list[str]) -> None:
        # 写之前再做一次 dedup + trim，避免不同入口的 set/replace 把脏数据
        # 写进 DB
        cleaned: list[str] = []
        seen: set[str] = set()
        for pid in ids:
            stripped = str(pid or "").strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            cleaned.append(stripped)
        config_store.set(_POOL_KEY, "\n".join(cleaned))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def list_profiles(self) -> list[dict]:
        """返回 ``[{"profile_id": "abc", "in_use": 1}, ...]``。"""
        with self._lock:
            ids = self._read_raw()
            return [
                {"profile_id": pid, "in_use": int(self._usage.get(pid, 0))}
                for pid in ids
            ]

    def add(self, profile_id: str) -> bool:
        """加一个 ID。返回 True 表示新增，False 表示已存在。"""
        normalized = str(profile_id or "").strip()
        if not normalized:
            raise ValueError("profile_id 不能为空")
        with self._lock:
            ids = self._read_raw()
            if normalized in ids:
                return False
            ids.append(normalized)
            self._write_raw(ids)
            return True

    def remove(self, profile_id: str) -> bool:
        normalized = str(profile_id or "").strip()
        if not normalized:
            return False
        with self._lock:
            ids = self._read_raw()
            if normalized not in ids:
                return False
            ids = [pid for pid in ids if pid != normalized]
            self._write_raw(ids)
            self._usage.pop(normalized, None)
            return True

    def replace_all(self, profile_ids: list[str]) -> list[str]:
        """整体替换池内容（前端"批量编辑"会用到）。返回最终入库的 ID 列表。"""
        with self._lock:
            self._write_raw(list(profile_ids or []))
            ids = self._read_raw()
            # in-memory usage 里只保留仍在池里的 key，避免内存泄漏
            for key in list(self._usage.keys()):
                if key not in ids:
                    self._usage.pop(key, None)
            return ids

    # ------------------------------------------------------------------
    # 并发分配
    # ------------------------------------------------------------------
    def acquire(self) -> str:
        """取一个**当前占用最少**的 profile。原子地把 usage[id] += 1。

        实现是 O(N)，N 一般很小（用户手动建 profile 不会超过 50 个），
        没必要上更复杂的最小堆。
        """
        with self._lock:
            ids = self._read_raw()
            if not ids:
                raise BitBrowserProfilePoolEmpty(
                    "BitBrowser profile 池为空，请先在「设置 → BitBrowser」里添加 profile ID"
                )
            best_pid = min(ids, key=lambda pid: self._usage.get(pid, 0))
            self._usage[best_pid] = self._usage.get(best_pid, 0) + 1
            return best_pid

    def release(self, profile_id: str) -> None:
        normalized = str(profile_id or "").strip()
        if not normalized:
            return
        with self._lock:
            current = self._usage.get(normalized, 0)
            if current <= 1:
                self._usage.pop(normalized, None)
            else:
                self._usage[normalized] = current - 1

    def acquire_or(self, fallback: Optional[str] = None) -> str:
        """池非空就 acquire，否则返回 fallback（不维护 usage 计数）。

        fallback 通常是用户在 UI 表单里直接填的 profile_id 或环境变量
        ``BIT_PROFILE_ID``。``"" / None`` 都视作"没 fallback"，此时
        池空就抛 ``BitBrowserProfilePoolEmpty``。
        """
        try:
            return self.acquire()
        except BitBrowserProfilePoolEmpty:
            fallback_clean = str(fallback or "").strip()
            if fallback_clean:
                return fallback_clean
            raise


bitbrowser_profile_pool = BitBrowserProfilePool()


def acquire_profile_for_browser_mode(
    browser_mode: str,
    *,
    fallback: str = "",
    log_fn=None,
) -> tuple[str, str]:
    """Return ``(profile_id, acquired_id)`` for BitBrowser modes."""
    if not str(browser_mode or "").strip().lower().startswith("bitbrowser_"):
        return "", ""
    fallback_id = str(fallback or "").strip() or os.environ.get("BIT_PROFILE_ID", "").strip()
    profile_id = bitbrowser_profile_pool.acquire_or(fallback=fallback_id)
    pool_ids = {
        item["profile_id"]
        for item in bitbrowser_profile_pool.list_profiles()
    }
    acquired_id = profile_id if profile_id in pool_ids else ""
    if log_fn:
        source = "设置里的 BitBrowser 号池" if acquired_id else "BIT_PROFILE_ID"
        log_fn(f"BitBrowser profile 已选择: {profile_id}（来源={source}）")
    return profile_id, acquired_id


def release_acquired_profile(profile_id: str, *, log_fn=None) -> None:
    if not str(profile_id or "").strip():
        return
    bitbrowser_profile_pool.release(profile_id)
    if log_fn:
        log_fn(f"BitBrowser profile 池已释放: {profile_id}")
"""模块级单例。``acquire`` 在进程内共享 in-memory 计数。"""
