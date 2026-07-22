"""临时脚本：精确时间线分析 10 并发任务的 profile 启动 vs 各类失败。"""
import sqlite3

con = sqlite3.connect(r"e:\work\gpt\account_manager.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

# 那个 00:16 的 10 并发任务
task_id = "task_1780071403081_00dbfd"
cur.execute("SELECT id, level, message, created_at FROM task_events WHERE task_id=? ORDER BY id", (task_id,))
rows = cur.fetchall()

# 只看付款阶段（注册完成后）：从 "开始 GoPay 付款" 之后
phase2 = False
print(f"=== {task_id} 付款阶段时间线（含关键事件）===")
for e in rows:
    m = e["message"]
    if "开始 GoPay 付款" in m:
        phase2 = True
    if not phase2:
        continue
    ts = e["created_at"][11:23]  # HH:MM:SS.mmm
    key = any(k in m for k in [
        "处理账号", "BitBrowser 启动 profile", "profile 已启动", "支付页面 readyState",
        "失败", "ERR_", "白屏", "TLS", "已选择 GoPay", "点击最终订阅", "等待支付页面",
        "支付页面关键元素", "代理", "池已释放",
    ])
    if key:
        lvl = "" if e["level"] == "info" else f"[{e['level']}]"
        print(f"{ts} {lvl}{m[:110]}")
con.close()
