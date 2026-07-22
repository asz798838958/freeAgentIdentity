"""
Kiro 账号切换 —— 写入 ~/.aws/sso/cache/ token 文件，Kiro IDE 自动识别
参考 kiro-account-manager (Tauri/Rust) 的 switch_kiro_account 实现
"""

import os
import json
import hashlib
import logging
import tempfile
import re
import platform
from typing import Tuple
from datetime import datetime, timezone, timedelta

import cbor2
from curl_cffi import requests as cffi_requests

from core.desktop_apps import build_desktop_app_state

logger = logging.getLogger(__name__)

OIDC_ENDPOINT = "https://oidc.us-east-1.amazonaws.com"
BUILDER_ID_START_URL = "https://view.awsapps.com/start"
DEFAULT_PROFILE_ARN = "arn:aws:codewhisperer:us-east-1:699475941385:profile/EHGA3GRVQMUK"


def _calculate_client_id_hash(start_url: str) -> str:
    """与 Kiro IDE 源码一致的 clientIdHash 计算"""
    input_str = json.dumps({"startUrl": start_url}, separators=(",", ":"))
    return hashlib.sha1(input_str.encode()).hexdigest()


def _get_cache_dir() -> str:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME", "")
    return os.path.join(home, ".aws", "sso", "cache")


def _kiro_install_paths() -> list[str]:
    system = platform.system()
    if system == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA", "")
        return [os.path.join(localappdata, "Programs", "Kiro", "Kiro.exe")]
    if system == "Darwin":
        home = os.path.expanduser("~")
        return [
            "/Applications/Kiro.app",
            os.path.join(home, "Applications", "Kiro.app"),
        ]
    return ["/usr/bin/kiro", os.path.expanduser("~/.local/bin/kiro")]


def _kiro_process_patterns() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        return [
            "/Applications/Kiro.app/Contents/MacOS/Kiro",
            os.path.join(os.path.expanduser("~"), "Applications", "Kiro.app", "Contents", "MacOS", "Kiro"),
        ]
    if system == "Windows":
        return ["Kiro.exe"]
    return ["kiro"]


def _atomic_write(filepath: str, content: str):
    """原子写入：先写临时文件，再 rename"""
    dir_path = os.path.dirname(filepath)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, filepath)
    except Exception:
        os.close(fd) if not os.path.exists(tmp_path) else None
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def refresh_kiro_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> Tuple[bool, dict]:
    """刷新 Kiro OIDC token，返回 (ok, {accessToken, refreshToken, expiresIn})"""
    if not refresh_token or not client_id or not client_secret:
        return False, {"error": "缺少 refreshToken / clientId / clientSecret"}
    try:
        r = cffi_requests.post(
            f"{OIDC_ENDPOINT}/token",
            json={
                "grantType": "refresh_token",
                "clientId": client_id,
                "clientSecret": client_secret,
                "refreshToken": refresh_token,
            },
            headers={
                "content-type": "application/json",
                "user-agent": "aws-sdk-rust/1.3.9 os/macOS lang/rust",
            },
            impersonate="chrome131",
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            return True, {
                "accessToken": data.get("accessToken", ""),
                "refreshToken": data.get("refreshToken", refresh_token),
                "expiresIn": data.get("expiresIn", 3600),
            }
        return False, {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return False, {"error": str(e)}


def _kiro_portal_headers(access_token: str) -> dict:
    return {
        "Accept": "application/cbor",
        "Content-Type": "application/cbor",
        "smithy-protocol": "rpc-v2-cbor",
        "Origin": "https://app.kiro.dev",
        "Referer": "https://app.kiro.dev/account/usage",
        "x-amz-user-agent": "aws-sdk-js/1.0.0 ua/2.1 os/macOS lang/js md/browser#Google-Chrome_146 m/N,M,E",
        "Authorization": f"Bearer {access_token}",
    }


def _serialize_kiro_portal_value(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _serialize_kiro_portal_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_serialize_kiro_portal_value(item) for item in value]
    return value


def _fetch_kiro_portal_user_id(access_token: str, session_token: str) -> str:
    if not access_token or not session_token:
        return ""
    try:
        page = cffi_requests.get(
            "https://app.kiro.dev/account/usage",
            headers={"user-agent": "Mozilla/5.0"},
            cookies={
                "AccessToken": access_token,
                "SessionToken": session_token,
                "Idp": "BuilderId",
            },
            impersonate="chrome124",
            timeout=20,
        )
        if page.status_code != 200:
            logger.error("获取 Kiro account/usage 页面失败: HTTP %s", page.status_code)
            return ""
        user_id = page.cookies.get("UserId", "")
        if user_id:
            return user_id
        match = re.search(r'<meta name="user-id" content="([^"]+)"', page.text)
        return match.group(1) if match else ""
    except Exception as e:
        logger.error(f"获取 Kiro portal user id 失败: {e}")
        return ""


def _call_kiro_portal_operation(
    operation: str,
    body: dict,
    *,
    access_token: str,
    session_token: str,
    user_id: str,
) -> dict | None:
    if not access_token or not session_token or not user_id:
        return None
    try:
        response = cffi_requests.post(
            f"https://app.kiro.dev/service/KiroWebPortalService/operation/{operation}",
            headers=_kiro_portal_headers(access_token),
            cookies={
                "AccessToken": access_token,
                "SessionToken": session_token,
                "Idp": "BuilderId",
                "UserId": user_id,
            },
            data=cbor2.dumps(body),
            impersonate="chrome124",
            timeout=20,
        )
        if response.status_code == 200:
            return _serialize_kiro_portal_value(cbor2.loads(response.content))
        try:
            payload = _serialize_kiro_portal_value(cbor2.loads(response.content))
        except Exception:
            payload = response.text[:200]
        logger.error("Kiro %s 失败: HTTP %s %s", operation, response.status_code, payload)
        return None
    except Exception as e:
        logger.error("Kiro %s 异常: %s", operation, e)
        return None


def get_kiro_portal_state(
    access_token: str,
    session_token: str,
    *,
    profile_arn: str = "",
) -> dict | None:
    """查询 Kiro Web Portal 的账号、套餐与 usage 信息。"""
    if not access_token or not session_token:
        return None

    actual_profile_arn = profile_arn or DEFAULT_PROFILE_ARN
    user_id = _fetch_kiro_portal_user_id(access_token, session_token)
    if not user_id:
        return {
            "available": False,
            "error": "无法从 Kiro Web Portal 会话中解析 UserId",
            "profile_arn": actual_profile_arn,
        }

    user_info = _call_kiro_portal_operation(
        "GetUserInfo",
        {"origin": "KIRO_IDE", "profileArn": actual_profile_arn},
        access_token=access_token,
        session_token=session_token,
        user_id=user_id,
    ) or {}
    usage_limits = _call_kiro_portal_operation(
        "GetUserUsageAndLimits",
        {"origin": "KIRO_IDE", "isEmailRequired": True, "profileArn": actual_profile_arn},
        access_token=access_token,
        session_token=session_token,
        user_id=user_id,
    ) or {}
    subscription_plans = _call_kiro_portal_operation(
        "GetAvailableSubscriptionPlans",
        {"profileArn": actual_profile_arn},
        access_token=access_token,
        session_token=session_token,
        user_id=user_id,
    ) or {}
    return {
        "available": bool(user_info or usage_limits or subscription_plans),
        "user_id": user_id,
        "profile_arn": actual_profile_arn,
        "user_info": user_info,
        "usage_limits": usage_limits,
        "available_subscription_plans": subscription_plans,
    }


def summarize_kiro_usage(portal_state: dict | None) -> dict | None:
    """提炼 Kiro Portal 返回，便于前端直接展示。"""
    if not portal_state:
        return None

    usage_limits = portal_state.get("usage_limits") or {}
    user_info = portal_state.get("user_info") or {}
    subscription_info = usage_limits.get("subscriptionInfo") or {}
    breakdowns = []
    for item in usage_limits.get("usageBreakdownList") or []:
        free_trial_info = item.get("freeTrialInfo") or {}
        current_usage = item.get("currentUsage")
        usage_limit = item.get("usageLimit")
        trial_usage_limit = free_trial_info.get("usageLimit")
        breakdowns.append({
            "resource_type": item.get("resourceType"),
            "display_name": item.get("displayName"),
            "display_name_plural": item.get("displayNamePlural"),
            "unit": item.get("unit"),
            "current_usage": current_usage,
            "usage_limit": usage_limit,
            "remaining_usage": (usage_limit - current_usage) if isinstance(current_usage, (int, float)) and isinstance(usage_limit, (int, float)) else None,
            "current_overages": item.get("currentOverages"),
            "overage_cap": item.get("overageCap"),
            "overage_rate": item.get("overageRate"),
            "next_reset_at": item.get("nextDateReset"),
            "trial_status": free_trial_info.get("freeTrialStatus"),
            "trial_expiry": free_trial_info.get("freeTrialExpiry"),
            "trial_current_usage": free_trial_info.get("currentUsage"),
            "trial_usage_limit": trial_usage_limit,
            "trial_remaining_usage": (
                trial_usage_limit - free_trial_info.get("currentUsage")
                if isinstance(free_trial_info.get("currentUsage"), (int, float)) and isinstance(trial_usage_limit, (int, float))
                else None
            ),
        })

    plans = []
    for item in (portal_state.get("available_subscription_plans") or {}).get("subscriptionPlans") or []:
        description = item.get("description") or {}
        pricing = item.get("pricing") or {}
        plans.append({
            "name": item.get("name"),
            "title": description.get("title"),
            "billing_interval": description.get("billingInterval"),
            "features": description.get("features") or [],
            "amount": pricing.get("amount"),
            "currency": pricing.get("currency"),
            "subscription_type": item.get("qSubscriptionType"),
        })

    return {
        "user_email": user_info.get("email"),
        "user_status": user_info.get("status"),
        "user_id": portal_state.get("user_id"),
        "plan_title": subscription_info.get("subscriptionTitle"),
        "subscription_type": subscription_info.get("type"),
        "upgrade_capability": subscription_info.get("upgradeCapability"),
        "overage_capability": subscription_info.get("overageCapability"),
        "overage_enabled": (usage_limits.get("overageConfiguration") or {}).get("overageEnabled"),
        "next_reset_at": usage_limits.get("nextDateReset"),
        "days_until_reset": usage_limits.get("daysUntilReset"),
        "breakdowns": breakdowns,
        "plans": plans,
    }


def switch_kiro_account(
    access_token: str,
    refresh_token: str,
    client_id: str = "",
    client_secret: str = "",
    provider: str = "BuilderId",
    auth_method: str = "IdC",
    region: str = "us-east-1",
    start_url: str = "",
) -> Tuple[bool, str]:
    """
    切换 Kiro 桌面应用账号（写入 token 文件，无需重启 IDE）。

    BuilderId 账号: auth_method="IdC", provider="BuilderId"
    Social 账号:    auth_method="social", provider="Google"/"GitHub"
    Enterprise:     auth_method="IdC", provider="Enterprise", 需提供 start_url
    """
    cache_dir = _get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    if auth_method == "IdC":
        actual_start_url = start_url or BUILDER_ID_START_URL
        client_id_hash = _calculate_client_id_hash(actual_start_url)

        token_data = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "authMethod": "IdC",
            "provider": provider,
            "clientIdHash": client_id_hash,
            "region": region,
        }
    else:
        token_data = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "profileArn": DEFAULT_PROFILE_ARN,
            "expiresAt": expires_at,
            "authMethod": "social",
            "provider": provider,
        }

    try:
        token_path = os.path.join(cache_dir, "kiro-auth-token.json")
        content = json.dumps(token_data, indent=2, ensure_ascii=False)
        _atomic_write(token_path, content)

        if auth_method == "IdC" and client_id and client_secret:
            client_expires = (
                datetime.now(timezone.utc) + timedelta(days=90)
            ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            client_reg = {
                "clientId": client_id,
                "clientSecret": client_secret,
                "expiresAt": client_expires,
            }
            client_path = os.path.join(cache_dir, f"{client_id_hash}.json")
            _atomic_write(
                client_path,
                json.dumps(client_reg, indent=2, ensure_ascii=False),
            )

        return True, "切换成功，Kiro IDE 将自动使用新账号"

    except Exception as e:
        logger.error(f"Kiro 账号切换失败: {e}")
        return False, f"切换失败: {str(e)}"


def restart_kiro_ide() -> Tuple[bool, str]:
    """关闭并重启 Kiro IDE，使新 token 立即生效"""
    import subprocess
    import platform
    import time

    sys = platform.system()

    try:
        if sys == "Darwin":
            subprocess.run(["osascript", "-e", 'quit app "Kiro"'], capture_output=True)
            time.sleep(2.0)
            kiro_app = "/Applications/Kiro.app"
            if os.path.exists(kiro_app):
                subprocess.Popen(["open", "-a", "Kiro"])
                return True, "Kiro IDE 已重启"
            return True, "已关闭 Kiro IDE（未找到应用路径，请手动启动）"

        elif sys == "Windows":
            subprocess.run(
                ["taskkill", "/IM", "Kiro.exe", "/F"],
                capture_output=True,
                creationflags=0x0800_0000,
            )
            time.sleep(1.5)
            localappdata = os.environ.get("LOCALAPPDATA", "")
            kiro_exe = os.path.join(localappdata, "Programs", "Kiro", "Kiro.exe")
            if os.path.exists(kiro_exe):
                subprocess.Popen([kiro_exe])
                return True, "Kiro IDE 已重启"
            return True, "已关闭 Kiro IDE（未找到应用路径，请手动启动）"

        else:
            subprocess.run(["pkill", "-f", "kiro"], capture_output=True)
            time.sleep(1.5)
            for path in ["/usr/bin/kiro", os.path.expanduser("~/.local/bin/kiro")]:
                if os.path.exists(path):
                    subprocess.Popen([path])
                    return True, "Kiro IDE 已重启"
            try:
                subprocess.Popen(["kiro"])
                return True, "Kiro IDE 已重启"
            except FileNotFoundError:
                return True, "已关闭 Kiro IDE（未找到应用路径，请手动启动）"

    except Exception as e:
        logger.error(f"Kiro IDE 重启失败: {e}")
        return False, f"重启失败: {str(e)}"


def read_current_kiro_account() -> dict | None:
    """读取当前 Kiro IDE 正在使用的账号 token"""
    token_path = os.path.join(_get_cache_dir(), "kiro-auth-token.json")
    if not os.path.exists(token_path):
        return None
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_kiro_desktop_state() -> dict:
    token_path = os.path.join(_get_cache_dir(), "kiro-auth-token.json")
    current = read_current_kiro_account() or {}
    state = build_desktop_app_state(
        app_id="kiro",
        app_name="Kiro",
        process_patterns=_kiro_process_patterns(),
        install_paths=_kiro_install_paths(),
        binary_names=["kiro"],
        config_paths=[_get_cache_dir(), token_path],
        current_account_present=bool(current.get("accessToken") or current.get("refreshToken")),
        extra={
            "token_path": token_path,
        },
    )
    state["available"] = True
    return state
