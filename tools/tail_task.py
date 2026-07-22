"""轮询某个 task 的事件流，按时间排序输出干净中文日志。"""
from __future__ import annotations

import json
import sys
import time
from urllib.request import urlopen


def fetch_events(task_id: str, base: str = "http://127.0.0.1:8000") -> list[dict]:
    url = f"{base}/api/tasks/{task_id}/events?limit=2000"
    with urlopen(url, timeout=10) as r:
        return json.load(r)


def fetch_status(task_id: str, base: str = "http://127.0.0.1:8000") -> dict:
    url = f"{base}/api/tasks/{task_id}"
    with urlopen(url, timeout=10) as r:
        return json.load(r)


def main(task_id: str, tail: int = 60) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    status = fetch_status(task_id)
    print(f"=== task={task_id} status={status.get('status')} progress={status.get('progress')} ===")
    raw = fetch_events(task_id)
    if isinstance(raw, dict):
        # 兼容 ``{events: [...], next_since: ...}`` 这种 wrapping
        events = raw.get("events") or raw.get("items") or []
    else:
        events = raw or []
    if not isinstance(events, list):
        print(f"events not a list: {type(events).__name__} keys={list(raw.keys()) if isinstance(raw, dict) else 'n/a'}")
        return 1
    print(f"=== total events: {len(events)}, showing last {min(tail, len(events))} ===")
    for ev in events[-tail:]:
        ts = (ev.get("created_at") or "").split("T", 1)[-1].split(".")[0]
        lvl = ev.get("level") or ""
        msg = ev.get("message") or ev.get("line") or ""
        print(f"  [{ts}] [{lvl}] {msg}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python tools/tail_task.py <task_id> [tail_count]")
        sys.exit(1)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    sys.exit(main(sys.argv[1], n))
