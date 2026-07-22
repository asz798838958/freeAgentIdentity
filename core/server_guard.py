from __future__ import annotations

import http.client
import socket
import sys
from typing import Sequence


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def parse_uvicorn_port(argv: Sequence[str] | None = None, default: int = DEFAULT_PORT) -> int:
    args = list(argv or [])
    for index, arg in enumerate(args):
        text = str(arg)
        if text == "--port" and index + 1 < len(args):
            try:
                return int(args[index + 1])
            except (TypeError, ValueError):
                return default
        if text.startswith("--port="):
            try:
                return int(text.split("=", 1)[1])
            except (TypeError, ValueError):
                return default
    return default


def is_main_app_uvicorn_target(argv: Sequence[str] | None = None) -> bool:
    args = [str(item) for item in (argv or [])]
    return any(item == "main:app" or item.endswith("main:app") for item in args)


def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def is_account_manager_healthy(host: str, port: int) -> bool:
    try:
        conn = http.client.HTTPConnection(host, int(port), timeout=1.0)
        conn.request("GET", "/api/health")
        response = conn.getresponse()
        body = response.read(512).decode("utf-8", errors="replace")
        return response.status < 500 and "account-manager-v2" in body
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def evaluate_duplicate_start(
    argv: Sequence[str] | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int | None = None,
    require_main_app_target: bool = True,
) -> tuple[bool, int, str]:
    args = list(argv if argv is not None else sys.argv)
    if require_main_app_target and not is_main_app_uvicorn_target(args):
        return False, 0, ""

    resolved_port = int(port or parse_uvicorn_port(args))
    if is_account_manager_healthy(host, resolved_port):
        return (
            True,
            0,
            f"Account Manager backend already running at http://{host}:{resolved_port}; skip duplicate start.",
        )

    if is_port_open(host, resolved_port):
        return (
            True,
            1,
            f"Port {host}:{resolved_port} is already in use by another process.",
        )

    return False, 0, ""


def guard_duplicate_start(
    argv: Sequence[str] | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int | None = None,
    require_main_app_target: bool = True,
) -> None:
    should_exit, code, message = evaluate_duplicate_start(
        argv,
        host=host,
        port=port,
        require_main_app_target=require_main_app_target,
    )
    if should_exit:
        if message:
            print(f"[ServerGuard] {message}", flush=True)
        raise SystemExit(code)
