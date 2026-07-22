import os
import sys
from contextlib import asynccontextmanager

# ★ 加载 .env 文件（在导入任何模块之前，确保所有 os.environ.get() 能读到配置）
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _key, _, _value = _line.partition("=")
                _key = _key.strip()
                _value = _value.strip().strip("\"'")
                if _key and _value and _key not in os.environ:
                    os.environ[_key] = _value
    except Exception:
        pass

# 把 stdout/stderr 强制成 utf-8（Windows 中文版默认是 gbk，碰到 ✗ ✓ 等
# 非 GBK 字符会抛 UnicodeEncodeError 让进程崩溃）。errors="replace" 双保险，
# 任何编码失败的字符替换成 ? 而不是抛错。
# 同时设置 PYTHONUTF8 环境变量，确保子进程也使用 UTF-8。
os.environ.setdefault("PYTHONUTF8", "1")
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
# 兜底：如果 reconfigure 不可用（PyInstaller 某些版本），用 wrapper 包一层
if sys.stdout is not None and getattr(sys.stdout, "encoding", "").lower() not in ("utf-8", "utf8"):
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
if sys.stderr is not None and getattr(sys.stderr, "encoding", "").lower() not in ("utf-8", "utf8"):
    try:
        import io
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

from core.server_guard import guard_duplicate_start

guard_duplicate_start()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# PyInstaller 静态分析钩子 — 让 modulefinder 跟踪到 Solver 子进程依赖（quart 等）
# 不会在运行时执行，只是给 PyInstaller 看
if False:  # pragma: no cover
    import services.turnstile_solver.api_solver  # noqa: F401
    import quart  # noqa: F401
    import patchright  # noqa: F401
    import rich  # noqa: F401

from api.account_checks import router as account_checks_router
from api.accounts import router as accounts_router
from api.actions import router as actions_router
from api.auth import router as auth_router
from api.config import router as config_router
from core.auth import AuthMiddleware
from api.health import router as health_router
from api.platforms import router as platforms_router
from api.provider_definitions import router as provider_definitions_router
from api.provider_settings import router as provider_settings_router
from api.system import router as system_router
from api.task_commands import router as task_commands_router
from api.tasks import router as tasks_router
from core.db import init_db
from core.registry import load_all
from providers.registry import load_all as load_providers


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_all()
    load_providers()
    print("[OK] 数据库初始化完成")
    from core.registry import list_platforms
    print(f"[OK] 已加载平台: {[p['name'] for p in list_platforms()]}")
    from core.scheduler import scheduler
    scheduler.start()
    from services.task_runtime import task_runtime
    task_runtime.start()
    from services.solver_manager import start_async
    start_async()
    from core.lifecycle import lifecycle_manager
    lifecycle_manager.start()
    yield
    from core.lifecycle import lifecycle_manager as _lifecycle_manager
    _lifecycle_manager.stop()
    from core.scheduler import scheduler as _scheduler
    _scheduler.stop()
    from services.task_runtime import task_runtime as _task_runtime
    _task_runtime.stop()
    from services.solver_manager import stop
    stop()


app = FastAPI(title="Account Manager", version="2.0.0", lifespan=lifespan)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router, prefix="/api")
app.include_router(account_checks_router, prefix="/api")
app.include_router(actions_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(platforms_router, prefix="/api")
app.include_router(provider_definitions_router, prefix="/api")
app.include_router(provider_settings_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(task_commands_router, prefix="/api")
app.include_router(system_router, prefix="/api")


_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(_static_dir, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        return FileResponse(os.path.join(_static_dir, "index.html"))


if __name__ == "__main__":
    import sys
    import uvicorn

    # 当 backend 被自己以 --solver 参数 spawn 时（PyInstaller 打包模式），
    # 不启动 FastAPI 主服务，而是作为 Turnstile Solver 子进程运行
    if len(sys.argv) > 1 and sys.argv[1] == "--solver":
        sys.argv = [sys.argv[0]] + sys.argv[2:]  # 把 --solver 摘掉，让 argparse 看到剩余参数
        from services.turnstile_solver.start import main as solver_main
        solver_main()
        sys.exit(0)

    guard_duplicate_start(["main:app", "--port", "8000"], require_main_app_target=False)
    uvicorn.run(app, host="0.0.0.0", port=8000)
