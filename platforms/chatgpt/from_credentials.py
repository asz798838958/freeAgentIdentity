#!/usr/bin/env python3
"""从已有 ChatGPT/Codex OAuth 凭据 JSON 生成 Agent Identity 凭证。

单文件实现，不依赖本仓库其他模块。
第三方依赖仅 PyNaCl：

    python -m pip install "PyNaCl>=1.5,<2"

支持输出：
- auth-json：codex-agent-identity-web 精简 auth.json
- certificate：本项目内部凭证
- sub2api：最新版 Sub2API 数据导入与 Agent Identity 导入双兼容 JSON
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nacl.bindings import crypto_box_seal_open
from nacl.bindings import crypto_sign_ed25519_pk_to_curve25519
from nacl.bindings import crypto_sign_ed25519_sk_to_curve25519
from nacl.bindings import crypto_sign_seed_keypair
from nacl.signing import SigningKey

CERTIFICATE_VERSION = 1
DEFAULT_AUTH_API_BASE_URL = "https://auth.openai.com/api/accounts"
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
USER_AGENT = "codex-agent-identity/1"
DEFAULT_PROXY_URL = os.environ.get("CODEX_AGENT_PROXY", "")


# 线程局部：批量转换时可为每条任务指定独立代理/会话。
_thread_proxy_url: threading.local = threading.local()


def set_thread_proxy_url(proxy_url: str | None) -> None:
    if proxy_url is not None:
        _thread_proxy_url.value = proxy_url.strip()
    elif hasattr(_thread_proxy_url, "value"):
        delattr(_thread_proxy_url, "value")


def get_thread_proxy_url() -> str | None:
    if hasattr(_thread_proxy_url, "value"):
        value = getattr(_thread_proxy_url, "value")
        return value.strip() or None
    env = os.environ.get("CODEX_AGENT_PROXY") or os.environ.get("HTTPS_PROXY")
    if isinstance(env, str) and env.strip():
        return env.strip()
    return None


def build_rotating_proxy_url(base_proxy_url: str, session_id: str | None = None) -> str:
    """规范化代理 URL。

    该家宽账号不接受 username 内嵌 session 后缀（会 407）。
    轮转依赖“每请求新建 TCP/CONNECT 连接”，session_id 仅用于日志隔离，不改账号。
    """
    from urllib.parse import quote, urlparse, urlunparse

    del session_id  # 保留参数兼容批量调用方
    raw = base_proxy_url.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        raise Error(f"代理 URL 无效：{base_proxy_url}")
    username = parsed.username or ""
    password = parsed.password or ""
    host = parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    auth = ""
    if username or password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    netloc = f"{auth}{host}{port}"
    return urlunparse((parsed.scheme or "http", netloc, "", "", "", ""))

ED25519_PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")


class Error(RuntimeError):
    pass


class ChineseArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return (
            super()
            .format_help()
            .replace("usage:", "用法：")
            .replace("options:", "选项：")
            .replace("show this help message and exit", "显示帮助信息并退出")
        )


def parse_args() -> argparse.Namespace:
    parser = ChineseArgumentParser(
        description=(
            "读取已有 access_token/id_token 凭据 JSON，"
            "注册 Agent Identity 并写出 identity 凭证。"
        )
    )
    parser.add_argument(
        "credentials",
        type=Path,
        nargs="?",
        default=None,
        metavar="凭据文件",
        help="包含 access_token 与 id_token 的 JSON；省略或传入 - 时从 stdin 读取",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("identity.json"),
        help="输出路径（默认：./identity.json）",
    )
    parser.add_argument(
        "--format",
        "--output-format",
        dest="output_format",
        choices=("auth-json", "certificate", "sub2api"),
        default="sub2api",
        help=(
            "输出格式：Sub2API 双入口兼容 JSON（默认）、"
            "Codex auth.json 或本项目 certificate"
        ),
    )
    parser.add_argument(
        "--auth-api-base-url",
        default=DEFAULT_AUTH_API_BASE_URL,
        help="Agent Identity 注册 API 地址",
    )
    parser.add_argument(
        "--proxy",
        default=DEFAULT_PROXY_URL,
        help="HTTP/HTTPS 代理（默认读取 CODEX_AGENT_PROXY；传空字符串禁用）",
    )
    parser.add_argument(
        "--codex-base-url",
        default=DEFAULT_CODEX_BASE_URL,
        help="Codex 后端地址",
    )
    return parser.parse_args()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def decode_jwt_payload(jwt: str) -> dict[str, Any]:
    parts = jwt.split(".")
    if len(parts) != 3 or not all(parts):
        raise Error("ID token 不是三段式 JWT")
    try:
        value = json.loads(b64url_decode(parts[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise Error("ID token payload 无效") from exc
    if not isinstance(value, dict):
        raise Error("ID token payload 必须是对象")
    return value


def parse_id_token_identity(id_token: str) -> dict[str, Any]:
    claims = decode_jwt_payload(id_token)
    auth = claims.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        raise Error("ID token 缺少 OpenAI auth claims")
    account_id = auth.get("chatgpt_account_id")
    user_id = (
        auth.get("chatgpt_user_id")
        or auth.get("chatgpt_account_user_id")
        or auth.get("user_id")
    )
    if not isinstance(account_id, str) or not account_id:
        raise Error("ID token 缺少 chatgpt_account_id")
    if not isinstance(user_id, str) or not user_id:
        raise Error("ID token 缺少 chatgpt_user_id")
    email = claims.get("email")
    profile = claims.get("https://api.openai.com/profile")
    if not isinstance(email, str) and isinstance(profile, dict):
        email = profile.get("email")
    plan_type = auth.get("chatgpt_plan_type")
    return {
        "account_id": account_id,
        "chatgpt_user_id": user_id,
        "email": email if isinstance(email, str) else None,
        "plan_type": plan_type if isinstance(plan_type, str) else "unknown",
        "chatgpt_account_is_fedramp": bool(
            auth.get("chatgpt_account_is_fedramp", False)
        ),
    }


def ssh_ed25519_public_key(signing_key: SigningKey) -> str:
    algorithm = b"ssh-ed25519"
    public_key = signing_key.verify_key.encode()
    blob = (
        len(algorithm).to_bytes(4, "big")
        + algorithm
        + len(public_key).to_bytes(4, "big")
        + public_key
    )
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


def sign_task_registration(
    signing_key: SigningKey, agent_runtime_id: str, timestamp: str
) -> str:
    payload = f"{agent_runtime_id}:{timestamp}".encode("utf-8")
    return base64.b64encode(signing_key.sign(payload).signature).decode("ascii")


def decrypt_task_id(signing_key: SigningKey, encrypted_task_id: str) -> str:
    seed = signing_key.encode()
    ed_public_key, ed_secret_key = crypto_sign_seed_keypair(seed)
    curve_public_key = crypto_sign_ed25519_pk_to_curve25519(ed_public_key)
    curve_secret_key = crypto_sign_ed25519_sk_to_curve25519(ed_secret_key)
    try:
        ciphertext = base64.b64decode(encrypted_task_id, validate=True)
        plaintext = crypto_box_seal_open(
            ciphertext,
            curve_public_key,
            curve_secret_key,
        )
        task_id = plaintext.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise Error("无法解密 task 注册响应") from exc
    if not task_id:
        raise Error("解密后的 task ID 为空")
    return task_id


def signing_key_pkcs8_base64(signing_key: SigningKey) -> str:
    private_key_der = ED25519_PKCS8_PREFIX + signing_key.encode()
    return base64.b64encode(private_key_der).decode("ascii")


def certificate_to_codex_auth_json(certificate: dict[str, Any]) -> dict[str, Any]:
    """导出与 codex-agent-identity-web 一致的精简 auth.json。"""
    identity = build_agent_identity_record(certificate)
    return {
        "auth_mode": "agentIdentity",
        "OPENAI_API_KEY": None,
        "agent_identity": identity,
    }


def email_key(email: str | None) -> str | None:
    if not isinstance(email, str) or not email.strip():
        return None
    out: list[str] = []
    prev_underscore = False
    for ch in email.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_underscore = False
        elif not prev_underscore:
            out.append("_")
            prev_underscore = True
    return "".join(out).strip("_") or None


def build_agent_identity_record(certificate: dict[str, Any]) -> dict[str, Any]:
    seed = base64.b64decode(certificate["private_key_seed"], validate=True)
    if len(seed) != 32:
        # auth-json / sub2api 也可能直接带 PKCS#8
        if "agent_private_key" in certificate:
            return {
                "agent_runtime_id": certificate["agent_runtime_id"],
                "agent_private_key": certificate["agent_private_key"],
                "account_id": certificate["account_id"],
                "chatgpt_user_id": certificate["chatgpt_user_id"],
                "email": certificate.get("email"),
                "plan_type": certificate.get("plan_type") or "unknown",
                "chatgpt_account_is_fedramp": bool(
                    certificate.get("chatgpt_account_is_fedramp", False)
                ),
                "task_id": certificate["task_id"],
            }
        raise Error("private_key_seed 必须是 32 字节")
    signing_key = SigningKey(seed)
    return {
        "agent_runtime_id": certificate["agent_runtime_id"],
        "agent_private_key": signing_key_pkcs8_base64(signing_key),
        "account_id": certificate["account_id"],
        "chatgpt_user_id": certificate["chatgpt_user_id"],
        "email": certificate.get("email"),
        "plan_type": certificate.get("plan_type") or "unknown",
        "chatgpt_account_is_fedramp": bool(
            certificate.get("chatgpt_account_is_fedramp", False)
        ),
        "task_id": certificate["task_id"],
    }


def certificate_to_sub2api_export(
    certificate: dict[str, Any],
    *,
    id_token: str | None = None,
    last_refresh: str | None = None,
    concurrency: int = 10,
    priority: int = 1,
    rate_multiplier: float = 1,
) -> dict[str, Any]:
    """导出最新版 Sub2API 两种导入入口都可识别的 Agent Identity JSON。"""
    del id_token
    auth_json = certificate_to_codex_auth_json(certificate)
    identity = auth_json["agent_identity"]
    account_id = identity["account_id"]
    email = identity.get("email")
    name = email or identity["agent_runtime_id"]
    refresh_at = last_refresh or utc_timestamp().replace("Z", ".000Z")
    if refresh_at.endswith("Z") and "." not in refresh_at:
        refresh_at = refresh_at[:-1] + ".000Z"

    credentials = {
        "auth_mode": "agentIdentity",
        "agent_runtime_id": identity["agent_runtime_id"],
        "agent_private_key": identity["agent_private_key"],
        "task_id": identity["task_id"],
        "account_id": account_id,
        "chatgpt_account_id": account_id,
        "chatgpt_user_id": identity["chatgpt_user_id"],
        "chatgpt_account_is_fedramp": identity["chatgpt_account_is_fedramp"],
        "email": email,
        "plan_type": identity["plan_type"],
        "workspace_id": account_id,
    }
    extra = {
        "email": email,
        "email_key": email_key(email if isinstance(email, str) else None),
        "name": name,
        "source": "chatgpt_web_session",
        "last_refresh": refresh_at,
        "account_id": account_id,
        "chatgpt_account_id": account_id,
        "workspace_id": account_id,
    }

    return {
        "type": "sub2api-data",
        "version": 1,
        "exported_at": utc_timestamp(),
        "proxies": [],
        "accounts": [
            {
                "name": name,
                "platform": "openai",
                "type": "oauth",
                "credentials": credentials,
                "extra": extra,
                "concurrency": concurrency,
                "priority": priority,
                "rate_multiplier": rate_multiplier,
                "auto_pause_on_expired": True,
            }
        ],
        **auth_json,
    }


def load_existing_identity(path: Path) -> dict[str, Any]:
    """读取已有 auth.json / certificate / 扁平 credentials，转为内部 certificate 形态。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Error(f"无法读取身份文件 {path}：{exc}") from exc
    if not isinstance(raw, dict):
        raise Error("身份文件顶层必须是对象")

    if raw.get("credential_type") == "codex_agent_identity" or "private_key_seed" in raw:
        return raw

    identity_obj = raw.get("agent_identity")
    if isinstance(identity_obj, dict):
        src = identity_obj
    elif raw.get("auth_mode") == "agentIdentity" or "agent_runtime_id" in raw:
        src = raw
    else:
        raise Error("无法识别的身份文件格式")

    required = (
        "agent_runtime_id",
        "agent_private_key",
        "account_id",
        "chatgpt_user_id",
        "task_id",
    )
    for key in required:
        value = src.get(key)
        if not isinstance(value, str) or not value.strip():
            raise Error(f"身份文件缺少有效字段：{key}")

    der = base64.b64decode(str(src["agent_private_key"]).strip(), validate=True)
    if len(der) != 48 or not der.startswith(ED25519_PKCS8_PREFIX):
        raise Error("agent_private_key 必须是 48 字节 Ed25519 PKCS#8")
    seed = der[16:]

    return {
        "version": CERTIFICATE_VERSION,
        "credential_type": "codex_agent_identity",
        "agent_runtime_id": src["agent_runtime_id"].strip(),
        "private_key_seed": base64.b64encode(seed).decode("ascii"),
        "task_id": src["task_id"].strip(),
        "account_id": src["account_id"].strip(),
        "chatgpt_user_id": src["chatgpt_user_id"].strip(),
        "email": src.get("email") if isinstance(src.get("email"), str) else None,
        "plan_type": src.get("plan_type")
        if isinstance(src.get("plan_type"), str)
        else "unknown",
        "chatgpt_account_is_fedramp": bool(src.get("chatgpt_account_is_fedramp", False)),
        "agent_private_key": str(src["agent_private_key"]).strip(),
    }


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
    attempts: int = 5,
    proxy_url: str | None = None,
) -> tuple[int, bytes]:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Connection": "close",
        **(headers or {}),
    }
    data = None
    if json_body is not None:
        data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    effective_proxy = proxy_url if proxy_url is not None else get_thread_proxy_url()

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            # 每次请求新建 opener，强制新连接；轮转家宽靠新 CONNECT 换出口。
            handlers: list[Any] = []
            if effective_proxy:
                proxy = build_rotating_proxy_url(effective_proxy)
                handlers.append(
                    urllib.request.ProxyHandler(
                        {"http": proxy, "https": proxy}
                    )
                )
            handlers.append(urllib.request.HTTPHandler())
            handlers.append(urllib.request.HTTPSHandler())
            opener = urllib.request.build_opener(*handlers)
            with opener.open(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code in {408, 425, 429, 500, 502, 503, 504} and attempt < attempts:
                time.sleep(min(2 ** attempt, 20) + attempt * 0.05)
                continue
            return exc.code, body
        except (
            urllib.error.URLError,
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
            ConnectionError,
            socket.timeout,
            TimeoutError,
            OSError,
        ) as exc:
            last_exc = exc
            if attempt == attempts:
                raise Error(
                    f"请求在重试 {attempts} 次后仍然失败：{method} {url}：{exc}"
                ) from exc
            time.sleep(min(2 ** attempt, 15))
    if last_exc is not None:
        raise Error(f"请求失败：{method} {url}：{last_exc}") from last_exc
    raise AssertionError("不应执行到这里")


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
    proxy_url: str | None = None,
) -> dict[str, Any]:
    status, body = http_request(
        method,
        url,
        headers=headers,
        json_body=json_body,
        timeout=timeout,
        proxy_url=proxy_url,
    )
    if status < 200 or status >= 300:
        detail = body.decode("utf-8", errors="replace")[:1000].strip()
        raise Error(f"{method} {url} 返回 HTTP {status}：{detail}")
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise Error(f"{method} {url} 返回的内容不是 JSON") from exc
    if not isinstance(value, dict):
        raise Error(f"{method} {url} 返回的 JSON 不是对象")
    return value


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            # 保持字段插入顺序，与 web 导出一致；不使用 sort_keys。
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        temp_name = None
    finally:
        os.umask(old_umask)
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def load_credentials(path: Path | None) -> dict[str, Any]:
    if path is None or str(path) == "-":
        raw = sys.stdin.read()
        source = "stdin"
    else:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise Error(f"无法读取凭据文件 {path}：{exc}") from exc
        source = str(path)

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Error(f"{source} 不是合法 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise Error(f"{source} 顶层必须是 JSON 对象")

    access_token = value.get("access_token")
    id_token = value.get("id_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise Error(f"{source} 缺少有效的 access_token")
    if not isinstance(id_token, str) or not id_token.strip():
        raise Error(f"{source} 缺少有效的 id_token")

    return {
        "access_token": access_token.strip(),
        "id_token": id_token.strip(),
    }


def register_identity(
    tokens: dict[str, Any],
    *,
    auth_api_base_url: str,
    codex_base_url: str,
) -> dict[str, Any]:
    identity = parse_id_token_identity(tokens["id_token"])
    signing_key = SigningKey.generate()
    registration_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    if identity["chatgpt_account_is_fedramp"]:
        registration_headers["X-OpenAI-Fedramp"] = "true"

    registration = http_json(
        "POST",
        f"{auth_api_base_url.rstrip('/')}/v1/agent/register",
        headers=registration_headers,
        json_body={
            "abom": {
                "agent_version": "standalone-script-1",
                "agent_harness_id": "codex-cli",
                "running_location": f"custom-{sys.platform}",
            },
            "agent_public_key": ssh_ed25519_public_key(signing_key),
            "capabilities": ["responsesapi"],
            "ttl": None,
        },
    )
    runtime_id = registration.get("agent_runtime_id")
    if not isinstance(runtime_id, str) or not runtime_id:
        raise Error("Agent 注册响应缺少 agent_runtime_id")

    timestamp = utc_timestamp()
    task = http_json(
        "POST",
        f"{auth_api_base_url.rstrip('/')}/v1/agent/{runtime_id}/task/register",
        json_body={
            "timestamp": timestamp,
            "signature": sign_task_registration(signing_key, runtime_id, timestamp),
        },
    )
    task_id = task.get("task_id") or task.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        encrypted = task.get("encrypted_task_id") or task.get("encryptedTaskId")
        if not isinstance(encrypted, str) or not encrypted:
            raise Error("task 注册响应缺少 task_id")
        task_id = decrypt_task_id(signing_key, encrypted)

    return {
        "version": CERTIFICATE_VERSION,
        "credential_type": "codex_agent_identity",
        "capabilities": ["responsesapi"],
        "created_at": utc_timestamp(),
        "agent_runtime_id": runtime_id,
        "private_key_seed": base64.b64encode(signing_key.encode()).decode("ascii"),
        "task_id": task_id,
        "account_id": identity["account_id"],
        "chatgpt_user_id": identity["chatgpt_user_id"],
        "email": identity["email"],
        "plan_type": identity["plan_type"],
        "chatgpt_account_is_fedramp": identity["chatgpt_account_is_fedramp"],
        "codex_base_url": codex_base_url.rstrip("/"),
        "auth_api_base_url": auth_api_base_url.rstrip("/"),
    }


def main() -> int:
    args = parse_args()

    proxy = (args.proxy or "").strip()
    if proxy:
        # 单条 CLI 也使用独立 session，避免粘连旧出口。
        session_id = f"cli-{os.getpid()}-{int(time.time() * 1000)}"
        set_thread_proxy_url(build_rotating_proxy_url(proxy, session_id))
    else:
        set_thread_proxy_url("")

    try:
        # 已有 identity/auth.json 时，可直接转 sub2api，无需再次注册。
        if args.credentials is not None and str(args.credentials) != "-":
            try:
                peek = json.loads(args.credentials.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                peek = None
            if isinstance(peek, dict) and (
                peek.get("auth_mode") == "agentIdentity"
                or "agent_identity" in peek
                or peek.get("credential_type") == "codex_agent_identity"
                or "private_key_seed" in peek
            ):
                certificate = load_existing_identity(args.credentials)
                id_token = None
                last_refresh = None
            else:
                tokens = load_credentials(args.credentials)
                certificate = register_identity(
                    tokens,
                    auth_api_base_url=args.auth_api_base_url,
                    codex_base_url=args.codex_base_url,
                )
                id_token = tokens.get("id_token")
                last_refresh = None
        else:
            tokens = load_credentials(args.credentials)
            certificate = register_identity(
                tokens,
                auth_api_base_url=args.auth_api_base_url,
                codex_base_url=args.codex_base_url,
            )
            id_token = tokens.get("id_token")
            last_refresh = None

        if args.output_format == "certificate":
            output = certificate
        elif args.output_format == "auth-json":
            output = certificate_to_codex_auth_json(certificate)
        else:
            output = certificate_to_sub2api_export(
                certificate,
                id_token=id_token if isinstance(id_token, str) else None,
                last_refresh=last_refresh,
            )

        write_private_json(args.output, output)
        print(f"凭证已写入：{args.output.expanduser().resolve()}")
        print("可在 Sub2API 的‘导入数据’或 Agent Identity 导入入口使用该文件。")
        if proxy:
            print(f"已使用代理：{urlparse_host(proxy)}")
        print("该凭证包含私钥，必须妥善保密。")
        return 0
    finally:
        set_thread_proxy_url(None)


def urlparse_host(proxy_url: str) -> str:
    from urllib.parse import urlparse

    raw = proxy_url if "://" in proxy_url else "http://" + proxy_url
    parsed = urlparse(raw)
    host = parsed.hostname or raw
    port = f":{parsed.port}" if parsed.port else ""
    return f"{host}{port}"


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Error as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        raise SystemExit(130)
