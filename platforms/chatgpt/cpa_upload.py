"""
CPA (Codex Protocol API) 上传功能
"""

import json
import base64
import logging
from typing import Tuple
from datetime import datetime, timezone, timedelta

from curl_cffi import requests as cffi_requests

logger = logging.getLogger(__name__)
CPA_TIMEZONE = timezone(timedelta(hours=8))


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return {}


def _get_config_value(key: str) -> str:
    try:
        from core.config_store import config_store
        return config_store.get(key, "")
    except Exception:
        return ""


def _extract_credential(account, key: str) -> str:
    """从 account 对象提取凭证，支持直接属性和 credentials 列表两种结构。"""
    val = getattr(account, key, None)
    if val:
        return str(val)
    creds = getattr(account, "credentials", None) or []
    if isinstance(creds, list):
        for c in creds:
            if isinstance(c, dict) and c.get("key") == key:
                return str(c.get("value", ""))
            if isinstance(c, dict) and key in c:
                return str(c[key])
    elif isinstance(creds, dict):
        if key in creds:
            return str(creds[key])
    return ""


def _first_text(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _format_cpa_timestamp(value) -> str:
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            text = str(value).strip()
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CPA_TIMEZONE).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception:
        return str(value).strip()


def generate_token_json(account) -> dict:
    """生成 CPA 格式的 Token JSON。"""
    email = getattr(account, "email", "")
    access_token = _extract_credential(account, "access_token")
    refresh_token = _extract_credential(account, "refresh_token")
    id_token = _extract_credential(account, "id_token")
    session_token = _extract_credential(account, "session_token")

    logger.info(f"[CPA] email={email}, access_token={'有' if access_token else '空'}"
                f"({len(access_token)}字符), user_id={getattr(account, 'user_id', '(无)')}")

    expired_str = _format_cpa_timestamp(
        getattr(account, "expired", None) or getattr(account, "expires_at", None)
    )
    account_id = _first_text(
        getattr(account, "account_id", None),
        getattr(account, "chatgpt_account_id", None),
        getattr(account, "user_id", None),
        _extract_credential(account, "account_id"),
        _extract_credential(account, "chatgpt_account_id"),
    )

    # 1) 从 id_token 解析 account_id (参考项目的做法)
    if not account_id and id_token:
        payload = _decode_jwt_payload(id_token)
        auth_info = payload.get("https://api.openai.com/auth", {})
        account_id = auth_info.get("chatgpt_account_id", "")
        logger.info(f"[CPA] id_token chatgpt_account_id={account_id or '(空)'}")

    # 2) fallback: 从 access_token 解析
    if not account_id and access_token:
        payload = _decode_jwt_payload(access_token)
        auth_info = payload.get("https://api.openai.com/auth", {})
        account_id = auth_info.get("chatgpt_account_id", "")
        logger.info(f"[CPA] access_token chatgpt_account_id={account_id or '(空)'}, "
                     f"auth_keys={list(auth_info.keys())}")
    # expired 从 access_token 的 exp 计算
    if not expired_str and access_token:
        payload = _decode_jwt_payload(access_token)
        exp_timestamp = payload.get("exp")
        if isinstance(exp_timestamp, int) and exp_timestamp > 0:
            exp_dt = datetime.fromtimestamp(
                exp_timestamp, tz=CPA_TIMEZONE)
            expired_str = exp_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 3) fallback: /backend-api/me (用 access_token 调)
    if not account_id and access_token:
        logger.info("[CPA] account_id 仍为空，尝试 /backend-api/me")
        try:
            resp = cffi_requests.get(
                "https://chatgpt.com/backend-api/me",
                headers={"authorization": f"Bearer {access_token}",
                         "accept": "application/json"},
                proxies=None, verify=False, timeout=15,
                impersonate="chrome110",
            )
            logger.info(f"[CPA] /backend-api/me status={resp.status_code}")
            if resp.status_code == 200:
                me = resp.json()
                for acct in me.get("accounts", {}).values():
                    aid = acct.get("account", {}).get("account_id", "")
                    if aid:
                        account_id = aid
                        break
                if not account_id:
                    account_id = me.get("id", "")
                logger.info(f"[CPA] /backend-api/me -> {account_id or '(空)'}")
        except Exception as e:
            logger.error(f"[CPA] /backend-api/me 失败: {e}")

    # 4) fallback: session_token 刷新拿新 access_token
    if not account_id:
        if session_token:
            logger.info("[CPA] 尝试 session_token 刷新获取 account_id")
            try:
                s = cffi_requests.Session(impersonate="chrome120")
                s.cookies.set("__Secure-next-auth.session-token",
                              session_token, domain=".chatgpt.com", path="/")
                resp = s.get("https://chatgpt.com/api/auth/session",
                             headers={"accept": "application/json"},
                             timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    new_at = data.get("accessToken", "")
                    if new_at:
                        p2 = _decode_jwt_payload(new_at)
                        ai2 = p2.get("https://api.openai.com/auth", {})
                        account_id = ai2.get("chatgpt_account_id", "")
                        if account_id:
                            access_token = new_at  # 用新 token
                            logger.info(f"[CPA] session 刷新成功: {account_id}")
                            exp2 = p2.get("exp")
                            if isinstance(exp2, int) and exp2 > 0:
                                expired_str = datetime.fromtimestamp(
                                    exp2, tz=CPA_TIMEZONE
                                ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
            except Exception as e:
                logger.error(f"[CPA] session 刷新失败: {e}")

    if not account_id:
        logger.warning("[CPA] ⚠️ account_id 最终为空! CPA 上传将失败")

    last_refresh = _format_cpa_timestamp(getattr(account, "last_refresh", None))
    if not last_refresh and access_token:
        payload = _decode_jwt_payload(access_token)
        iat_timestamp = payload.get("iat")
        if isinstance(iat_timestamp, int) and iat_timestamp > 0:
            last_refresh = _format_cpa_timestamp(iat_timestamp)
    if not last_refresh:
        last_refresh = datetime.now(tz=CPA_TIMEZONE).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    return {
        "access_token": access_token,
        "account_id": account_id,
        "email": email,
        "expired": expired_str,
        "id_token": id_token,
        "last_refresh": last_refresh,
        "refresh_token": refresh_token,
        "type": "codex",
    }


def upload_to_cpa(
    token_data: dict,
    api_url: str = None,
    api_key: str = None,
    proxy: str = None,
) -> Tuple[bool, str]:
    """上传单个账号到 CPA 管理平台（不走代理）。"""
    if not api_url:
        api_url = _get_config_value("cpa_api_url")
    if not api_key:
        api_key = _get_config_value("cpa_api_key")
    if not api_url:
        return False, "CPA API URL 未配置"

    # 上传前检查 account_id
    if not token_data.get("account_id"):
        return False, "account_id 为空，无法上传 CPA（JWT 和所有 fallback 均未获取到）"

    upload_url = f"{api_url.rstrip('/')}/v0/management/auth-files"
    filename = f"{token_data['email']}.json"
    file_content = json.dumps(token_data, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Authorization": f"Bearer {api_key or ''}",
        "Content-Type": "application/json",
    }

    logger.info(f"[CPA] 上传: email={token_data['email']}, "
                f"account_id={token_data.get('account_id','')}")

    try:
        from urllib.parse import quote
        target_url = f"{upload_url}?name={quote(filename)}"
        response = cffi_requests.post(
            target_url,
            headers=headers,
            data=file_content.encode("utf-8"),
            proxies=None,
            verify=False,
            timeout=30,
            impersonate="chrome110",
        )
        if response.status_code in (200, 201, 207):
            return True, "上传成功"
        error_msg = f"上传失败: HTTP {response.status_code}"
        try:
            error_detail = response.json()
            if isinstance(error_detail, dict):
                error_msg = error_detail.get("message", error_msg)
        except Exception:
            error_msg = f"{error_msg} - {response.text[:200]}"
        return False, error_msg
    except Exception as e:
        logger.error(f"CPA 上传异常: {e}")
        return False, f"上传异常: {str(e)}"


def upload_to_team_manager(
    account, api_url: str = None, api_key: str = None,
) -> Tuple[bool, str]:
    """上传单账号到 Team Manager（直连，不走代理）。"""
    if not api_url:
        api_url = _get_config_value("team_manager_url")
    if not api_key:
        api_key = _get_config_value("team_manager_key")
    if not api_url:
        return False, "Team Manager API URL 未配置"
    if not api_key:
        return False, "Team Manager API Key 未配置"

    email = getattr(account, "email", "")
    access_token = _extract_credential(account, "access_token")
    if not access_token:
        return False, "账号缺少 access_token"

    url = api_url.rstrip("/") + "/api/accounts/import"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    payload = {
        "import_type": "single",
        "email": email,
        "access_token": access_token,
        "session_token": _extract_credential(account, "session_token"),
        "refresh_token": _extract_credential(account, "refresh_token"),
        "client_id": getattr(account, "client_id", ""),
    }
    try:
        resp = cffi_requests.post(url, headers=headers, json=payload,
                                  proxies=None, verify=False, timeout=30,
                                  impersonate="chrome110")
        if resp.status_code in (200, 201):
            return True, "上传成功"
        error_msg = f"上传失败: HTTP {resp.status_code}"
        try:
            detail = resp.json()
            if isinstance(detail, dict):
                error_msg = detail.get("message", error_msg)
        except Exception:
            error_msg = f"{error_msg} - {resp.text[:200]}"
        return False, error_msg
    except Exception as e:
        logger.error(f"Team Manager 上传异常: {e}")
        return False, f"上传异常: {str(e)}"


def test_cpa_connection(api_url: str, api_token: str, proxy: str = None) -> Tuple[bool, str]:
    """测试 CPA 连接（不走代理）"""
    if not api_url:
        return False, "API URL 不能为空"
    if not api_token:
        return False, "API Token 不能为空"
    api_url = api_url.rstrip("/")
    test_url = f"{api_url}/v0/management/auth-files"
    headers = {"Authorization": f"Bearer {api_token}"}
    try:
        response = cffi_requests.options(test_url, headers=headers,
                                         proxies=None, verify=False,
                                         timeout=10, impersonate="chrome110")
        if response.status_code in (200, 204, 401, 403, 405):
            if response.status_code == 401:
                return False, "连接成功，但 API Token 无效"
            return True, "CPA 连接测试成功"
        return False, f"服务器返回异常状态码: {response.status_code}"
    except cffi_requests.exceptions.ConnectionError as e:
        return False, f"无法连接到服务器: {str(e)}"
    except cffi_requests.exceptions.Timeout:
        return False, "连接超时，请检查网络配置"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"
