"""Dump 最近成功注册 task 的 payload 模板，方便复刻调用。"""
from __future__ import annotations

import json
import sqlite3
import sys


def main(db_path: str = "account_manager.db") -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    print("=== mailbox provider_settings ===")
    for r in cur.execute(
        "SELECT id, provider_key, display_name, enabled, is_default, "
        "length(config_json) AS cfg_len FROM provider_settings "
        "WHERE provider_type='mailbox'"
    ):
        print(r)
    print()

    print("=== latest 5 chatgpt register tasks ===")
    cur.execute(
        "SELECT id, status, success_count, error_count, substr(payload_json, 1, 1500) "
        "FROM tasks WHERE type='register' AND platform='chatgpt' "
        "ORDER BY id DESC LIMIT 5"
    )
    for tid, status, sc, ec, payload_str in cur.fetchall():
        print(f"--- task id={tid} status={status} success={sc} error={ec} ---")
        try:
            print(json.dumps(json.loads(payload_str), indent=2, ensure_ascii=False))
        except Exception:
            print(payload_str)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "account_manager.db"))
