"""
Cursor 账号切换 —— 写入本地配置文件，Cursor IDE 自动识别
支持 macOS / Windows / Linux
"""

import os
import json
import logging
import tempfile
import platform
import subprocess
import time
from typing import Tuple

from core.desktop_apps import build_desktop_app_state

logger = logging.getLogger(__name__)


def _cursor_headers(token: str) -> dict:
    return {
        "Cookie": f"WorkosCursorSessionToken={token}",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36",
    }


def _get_cursor_config_dir() -> str:
    """获取 Cursor 配置目录路径"""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        home = os.path.expanduser("~")
        return os.path.join(home, "Library", "Application Support", "Cursor", "User")
    
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "Cursor", "User")
    
    else:  # Linux
        home = os.path.expanduser("~")
        config_home = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        return os.path.join(config_home, "Cursor", "User")


def _get_cursor_storage_path() -> str:
    """获取 Cursor storage.json 路径"""
    config_dir = _get_cursor_config_dir()
    return os.path.join(config_dir, "globalStorage", "storage.json")


def _cursor_install_paths() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        home = os.path.expanduser("~")
        return [
            "/Applications/Cursor.app",
            os.path.join(home, "Applications", "Cursor.app"),
        ]
    if system == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA", "")
        return [os.path.join(localappdata, "Programs", "Cursor", "Cursor.exe")]
    return ["/usr/bin/cursor", os.path.expanduser("~/.local/bin/cursor")]


def _cursor_process_patterns() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        return [
            "/Applications/Cursor.app/Contents/MacOS/Cursor",
            os.path.join(os.path.expanduser("~"), "Applications", "Cursor.app", "Contents", "MacOS", "Cursor"),
        ]
    if system == "Windows":
        return ["Cursor.exe"]
    return ["cursor"]


def _atomic_write(filepath: str, content: str):
    """原子写入：先写临时文件，再 rename"""
    dir_path = os.path.dirname(filepath)
    os.makedirs(dir_path, exist_ok=True)
    
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.close(fd)
        except:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def switch_cursor_account(token: str) -> Tuple[bool, str]:
    """
    切换 Cursor 账号（写入 storage.json，需要重启 Cursor）
    
    Args:
        token: WorkosCursorSessionToken
    
    Returns:
        (success, message)
    """
    try:
        storage_path = _get_cursor_storage_path()
        
        # 读取现有配置
        storage_data = {}
        if os.path.exists(storage_path):
            try:
                with open(storage_path, "r", encoding="utf-8") as f:
                    storage_data = json.load(f)
            except Exception as e:
                logger.warning(f"读取现有配置失败，将创建新配置: {e}")
        
        # 更新 token
        storage_data["workos.sessionToken"] = token
        
        # 原子写入
        content = json.dumps(storage_data, indent=2, ensure_ascii=False)
        _atomic_write(storage_path, content)
        
        return True, "切换成功，请重启 Cursor IDE 使新账号生效"
    
    except Exception as e:
        logger.error(f"Cursor 账号切换失败: {e}")
        return False, f"切换失败: {str(e)}"


def restart_cursor_ide() -> Tuple[bool, str]:
    """关闭并重启 Cursor IDE"""
    system = platform.system()
    
    try:
        if system == "Darwin":  # macOS
            # 关闭 Cursor
            subprocess.run(
                ["osascript", "-e", 'quit app "Cursor"'],
                capture_output=True,
                timeout=5
            )
            time.sleep(2.0)
            
            # 启动 Cursor
            cursor_app = "/Applications/Cursor.app"
            if os.path.exists(cursor_app):
                subprocess.Popen(["open", "-a", "Cursor"])
                return True, "Cursor IDE 已重启"
            return True, "已关闭 Cursor IDE（未找到应用路径，请手动启动）"
        
        elif system == "Windows":
            # 关闭 Cursor
            subprocess.run(
                ["taskkill", "/IM", "Cursor.exe", "/F"],
                capture_output=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=5
            )
            time.sleep(1.5)
            
            # 启动 Cursor
            localappdata = os.environ.get("LOCALAPPDATA", "")
            cursor_exe = os.path.join(localappdata, "Programs", "Cursor", "Cursor.exe")
            if os.path.exists(cursor_exe):
                subprocess.Popen([cursor_exe])
                return True, "Cursor IDE 已重启"
            return True, "已关闭 Cursor IDE（未找到应用路径，请手动启动）"
        
        else:  # Linux
            # 关闭 Cursor
            subprocess.run(["pkill", "-f", "cursor"], capture_output=True, timeout=5)
            time.sleep(1.5)
            
            # 启动 Cursor
            for path in ["/usr/bin/cursor", os.path.expanduser("~/.local/bin/cursor")]:
                if os.path.exists(path):
                    subprocess.Popen([path])
                    return True, "Cursor IDE 已重启"
            
            try:
                subprocess.Popen(["cursor"])
                return True, "Cursor IDE 已重启"
            except FileNotFoundError:
                return True, "已关闭 Cursor IDE（未找到应用路径，请手动启动）"
    
    except Exception as e:
        logger.error(f"Cursor IDE 重启失败: {e}")
        return False, f"重启失败: {str(e)}"


def read_current_cursor_account() -> dict | None:
    """读取当前 Cursor IDE 正在使用的账号 token"""
    storage_path = _get_cursor_storage_path()
    
    if not os.path.exists(storage_path):
        return None
    
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            storage_data = json.load(f)
        
        token = storage_data.get("workos.sessionToken")
        if token:
            return {"token": token}
        return None
    
    except Exception as e:
        logger.error(f"读取 Cursor 配置失败: {e}")
        return None


def get_cursor_desktop_state() -> dict:
    current = read_current_cursor_account() or {}
    storage_path = _get_cursor_storage_path()
    config_dir = _get_cursor_config_dir()
    state = build_desktop_app_state(
        app_id="cursor",
        app_name="Cursor",
        process_patterns=_cursor_process_patterns(),
        install_paths=_cursor_install_paths(),
        binary_names=["cursor"],
        config_paths=[config_dir, storage_path],
        current_account_present=bool(current.get("token")),
        extra={
            "storage_path": storage_path,
        },
    )
    state["available"] = True
    return state


def get_cursor_user_info(token: str) -> dict | None:
    """通过 token 获取用户信息"""
    from curl_cffi import requests as curl_req
    
    try:
        r = curl_req.get(
            "https://cursor.com/api/auth/me",
            headers=_cursor_headers(token),
            impersonate="chrome124",
            timeout=15,
        )
        
        if r.status_code == 200:
            return r.json()
        return None
    
    except Exception as e:
        logger.error(f"获取 Cursor 用户信息失败: {e}")
        return None


def get_cursor_billing_info(token: str) -> dict | None:
    """获取 Cursor 套餐、试用与账单状态。"""
    from curl_cffi import requests as curl_req

    try:
        r = curl_req.get(
            "https://cursor.com/api/auth/stripe",
            headers={
                **_cursor_headers(token),
                "accept": "application/json",
                "content-type": "application/json",
            },
            impersonate="chrome124",
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        logger.error("获取 Cursor 套餐状态失败: HTTP %s %s", r.status_code, r.text[:200])
        return None
    except Exception as e:
        logger.error(f"获取 Cursor 套餐状态失败: {e}")
        return None


def has_cursor_valid_payment_method(token: str) -> bool | None:
    """查询 Cursor 是否已绑定有效支付方式。"""
    from curl_cffi import requests as curl_req

    try:
        r = curl_req.get(
            "https://cursor.com/api/auth/has_valid_payment_method",
            headers={"accept": "application/json", **_cursor_headers(token)},
            impersonate="chrome124",
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            return bool(data.get("hasValidPaymentMethod"))
        logger.error("获取 Cursor 支付方式状态失败: HTTP %s %s", r.status_code, r.text[:200])
        return None
    except Exception as e:
        logger.error(f"获取 Cursor 支付方式状态失败: {e}")
        return None


def get_cursor_usage(token: str, user_id: str) -> dict | None:
    """查询 Cursor usage 数据。"""
    from curl_cffi import requests as curl_req

    if not user_id:
        return None

    try:
        r = curl_req.get(
            f"https://cursor.com/api/usage?user={user_id}",
            headers={"accept": "application/json", **_cursor_headers(token)},
            impersonate="chrome124",
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        logger.error("获取 Cursor usage 失败: HTTP %s %s", r.status_code, r.text[:200])
        return None
    except Exception as e:
        logger.error(f"获取 Cursor usage 失败: {e}")
        return None


def summarize_cursor_usage(usage_data: dict | None) -> dict | None:
    """提炼更适合 UI 展示的 Cursor usage 摘要。"""
    if not usage_data:
        return None

    summary = {
        "start_of_month": usage_data.get("startOfMonth"),
        "models": {},
        "has_any_limit": False,
    }
    for model_name, value in usage_data.items():
        if model_name == "startOfMonth" or not isinstance(value, dict):
            continue
        max_token_usage = value.get("maxTokenUsage")
        max_request_usage = value.get("maxRequestUsage")
        model_summary = {
            "num_requests": value.get("numRequests"),
            "num_requests_total": value.get("numRequestsTotal"),
            "num_tokens": value.get("numTokens"),
            "max_request_usage": max_request_usage,
            "max_token_usage": max_token_usage,
            "remaining_requests": None,
            "remaining_tokens": None,
        }
        if isinstance(max_request_usage, (int, float)) and isinstance(value.get("numRequests"), (int, float)):
            model_summary["remaining_requests"] = max_request_usage - value["numRequests"]
        if isinstance(max_token_usage, (int, float)) and isinstance(value.get("numTokens"), (int, float)):
            model_summary["remaining_tokens"] = max_token_usage - value["numTokens"]
        if max_token_usage is not None or max_request_usage is not None:
            summary["has_any_limit"] = True
        summary["models"][model_name] = model_summary
    return summary


def generate_cursor_checkout_link(
    token: str,
    *,
    tier: str = "pro",
    allow_trial: bool = True,
    allow_automatic_payment: bool = False,
    yearly: bool = False,
) -> str | None:
    """生成 Cursor Pro 结账链接，可用于 7 天试用入口。"""
    from curl_cffi import requests as curl_req

    try:
        r = curl_req.post(
            "https://cursor.com/api/checkout",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "origin": "https://cursor.com",
                "referer": "https://cursor.com/dashboard",
                **_cursor_headers(token),
            },
            json={
                "tier": tier,
                "allowTrial": allow_trial,
                "allowAutomaticPayment": allow_automatic_payment,
                "yearly": yearly,
            },
            impersonate="chrome124",
            timeout=20,
        )
        if r.status_code == 200:
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            if isinstance(payload, str) and payload.startswith("https://"):
                return payload
        logger.error("生成 Cursor 结账链接失败: HTTP %s %s", r.status_code, r.text[:300])
        return None
    except Exception as e:
        logger.error(f"生成 Cursor 结账链接失败: {e}")
        return None
