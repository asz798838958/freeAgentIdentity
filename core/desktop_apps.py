from __future__ import annotations

import csv
import io
import os
import platform
import shutil
import subprocess
from typing import Iterable


def _run_command(cmd: list[str]) -> tuple[bool, str]:
    creationflags = 0x08000000 if platform.system() == "Windows" else 0
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        return completed.returncode == 0, (completed.stdout or completed.stderr or "").strip()
    except Exception:
        return False, ""


def _normalize_process_pattern(value: str) -> str:
    raw = str(value or "").strip().strip('"').strip("'")
    if not raw:
        return ""
    normalized = raw.replace("\\", "/").rstrip("/")
    if "/" in normalized:
        return normalized.lower()
    name = os.path.basename(normalized)
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name.lower()


def _list_process_entries() -> list[str]:
    system = platform.system()
    if system == "Windows":
        ok, output = _run_command(["tasklist", "/FO", "CSV", "/NH"])
        if not ok:
            return []
        reader = csv.reader(io.StringIO(output))
        return [row[0].strip() for row in reader if row and row[0].strip()]

    ok, output = _run_command(["ps", "-ax", "-o", "comm="])
    if not ok:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def is_process_running(process_patterns: Iterable[str]) -> bool:
    patterns = [_normalize_process_pattern(item) for item in process_patterns]
    patterns = [pattern for pattern in patterns if pattern]
    if not patterns:
        return False

    for entry in _list_process_entries():
        normalized_entry = _normalize_process_pattern(entry)
        if not normalized_entry:
            continue
        for pattern in patterns:
            if "/" in pattern:
                if normalized_entry == pattern:
                    return True
                continue
            if normalized_entry == pattern:
                return True
            if normalized_entry.endswith(f"/{pattern}"):
                return True
            if normalized_entry.endswith(f"/{pattern}.exe"):
                return True
            if normalized_entry.endswith(f".app/contents/macos/{pattern}"):
                return True
            if normalized_entry.endswith(f".app/contents/macos/{pattern}.exe"):
                return True
    return False


def existing_paths(paths: Iterable[str]) -> list[str]:
    results: list[str] = []
    for raw in paths:
        path = str(raw or "").strip()
        if path and os.path.exists(path):
            results.append(path)
    return results


def existing_binaries(names: Iterable[str]) -> list[str]:
    results: list[str] = []
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        resolved = shutil.which(name)
        if resolved:
            results.append(resolved)
    return results


def build_desktop_app_state(
    *,
    app_id: str,
    app_name: str,
    process_patterns: Iterable[str],
    install_paths: Iterable[str] = (),
    binary_names: Iterable[str] = (),
    config_paths: Iterable[str] = (),
    current_account_present: bool = False,
    extra: dict | None = None,
) -> dict:
    install_candidates = existing_paths(install_paths)
    binary_candidates = existing_binaries(binary_names)
    config_candidates = existing_paths(config_paths)
    running = is_process_running(process_patterns)
    installed = bool(install_candidates or binary_candidates or config_candidates)
    configured = bool(config_candidates or current_account_present)

    state = {
        "app_id": app_id,
        "app_name": app_name,
        "running": running,
        "installed": installed,
        "configured": configured,
        "ready": installed and configured,
        "current_account_present": bool(current_account_present),
        "install_paths": install_candidates,
        "binaries": binary_candidates,
        "config_paths": config_candidates,
        "status_label": "已打开" if running else "未打开",
        "ready_label": "已就绪" if installed and configured else ("未配置" if installed else "未安装"),
    }
    if extra:
        state.update(extra)
    return state
