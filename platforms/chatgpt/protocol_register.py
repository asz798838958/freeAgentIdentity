"""ChatGPT email registration through the OpenAI web protocol.

Signup remains direct HTTP; a hidden Chromium page is used only to execute the
official Sentinel JavaScript required for the create-account security token.
"""
from __future__ import annotations

import base64
import json
import random
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Callable
from urllib.parse import urlencode, urljoin

from curl_cffi import requests

from .constants import (
    CHATGPT_APP,
    OPENAI_API_ENDPOINTS,
    OPENAI_AUTH,
    SENTINEL_BASE,
    SENTINEL_FRAME_URL,
    SENTINEL_REQ_URL,
    SENTINEL_SDK_URL,
)


FIRST_NAMES = (
    "James", "John", "Robert", "Michael", "David", "William", "Richard",
    "Joseph", "Thomas", "Daniel", "Matthew", "Anthony", "Mary", "Linda",
    "Jennifer", "Sarah", "Jessica", "Elizabeth",
)
LAST_NAMES = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Martin",
    "Lee", "White",
)


def _random_profile() -> tuple[str, str]:
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    age = random.randint(24, 36)
    birthdate = (datetime.now() - timedelta(days=age * 365)).strftime("%Y-%m-%d")
    return name, birthdate


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return {}


def _response_json(response) -> dict:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _response_error(response, payload: dict | None = None) -> str:
    data = payload or _response_json(response)
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or "").strip()
        if code and message and code not in message:
            return f"{code}: {message}"
        if message or code:
            return message or code
    if isinstance(error, str) and error:
        return error
    text = str(getattr(response, "text", "") or "").strip()
    return text[:300] or f"HTTP {getattr(response, 'status_code', 0)}"


class _SentinelTokenGenerator:
    """Generate the requirements/enforcement PoW used by OpenAI Sentinel."""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a32(text: str) -> str:
        value = 2166136261
        for char in text:
            value ^= ord(char)
            value = (value * 16777619) & 0xFFFFFFFF
        value ^= value >> 16
        value = (value * 2246822507) & 0xFFFFFFFF
        value ^= value >> 13
        value = (value * 3266489909) & 0xFFFFFFFF
        value ^= value >> 16
        return f"{value & 0xFFFFFFFF:08x}"

    @staticmethod
    def _encode(value) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _fingerprint(self) -> list:
        perf_now = 1000 + random.random() * 49000
        return [
            "1920x1080",
            time.strftime(
                "%a, %d %b %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)",
                time.gmtime(),
            ),
            4294705152,
            random.random(),
            self.user_agent,
            SENTINEL_SDK_URL,
            None,
            None,
            "en-US",
            "en-US,en",
            random.random(),
            "webkitTemporaryStorage−undefined",
            "location",
            "Object",
            perf_now,
            self.sid,
            "",
            random.choice((4, 8, 12, 16)),
            int(time.time() * 1000 - perf_now),
        ]

    def _reference_fingerprint(self) -> list:
        """25-field fingerprint used by the current Sentinel SDK."""
        now = datetime.now().astimezone()
        perf_now = round(
            time.time() * 1000 - 1_000_000 + random.uniform(1000, 5000), 1
        )
        time_origin = round(time.time() * 1000 - 50_000, 1)
        return [
            3000,
            str(now),
            4294705152,
            0,
            self.user_agent,
            SENTINEL_SDK_URL,
            None,
            "en-US",
            "en-US,en",
            0,
            "webkitTemporaryStorage\u2212undefined",
            "location",
            "Object",
            perf_now,
            self.sid,
            "",
            8,
            time_origin,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]

    def _solve_reference_pow(self, seed: str, difficulty: str, data: list) -> str:
        started = time.perf_counter()
        target = str(difficulty or "0")
        for nonce in range(500_000):
            data[3] = nonce
            data[9] = round((time.perf_counter() - started) * 1000)
            encoded = self._encode(data)
            digest = self._fnv1a32(str(seed or "") + encoded)
            if digest[: len(target)] <= target:
                return encoded + "~S"
        return self._encode("e")

    def requirements(self) -> str:
        config = self._reference_fingerprint()
        config[3] = 1
        config[9] = round(5 + random.random() * 45)
        return "gAAAAAC" + self._solve_reference_pow(
            str(random.random()), "0", config
        )

    def enforcement(self, seed: str, difficulty: str) -> str:
        return "gAAAAAB" + self._solve_reference_pow(
            seed, difficulty, self._reference_fingerprint()
        )


class _SentinelBrowserRuntime:
    """Run the official Sentinel SDK in a hidden browser context.

    The signup flow itself remains direct curl_cffi HTTP. Chromium is used
    only as the JavaScript/browser runtime required to produce Sentinel's
    encrypted turnstile proof and optional session-observer token.
    """

    _sdk_lock = threading.Lock()
    _sdk_code: str | None = None

    def __init__(self, session, *, user_agent: str, proxy: str | None):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        del proxy  # VM execution itself performs no network requests.
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=user_agent,
            locale="en-US",
            viewport={"width": 1920, "height": 1080},
        )
        self._page = self._context.new_page()
        try:
            self._page.goto(
                f"{OPENAI_AUTH}/about-you",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
        except Exception:
            self._page.goto("https://auth.openai.com/about-you", wait_until="domcontentloaded")

        with self._sdk_lock:
            if self._sdk_code is None:
                response = session.get(SENTINEL_SDK_URL, timeout=30)
                if getattr(response, "status_code", 0) >= 400:
                    raise RuntimeError(
                        f"Sentinel SDK 获取失败: HTTP {response.status_code}"
                    )
                code = str(getattr(response, "text", "") or "")
                if not code:
                    raise RuntimeError("Sentinel SDK 返回为空")
                self.__class__._sdk_code = code
            sdk_code = self._sdk_code
        hook = "t.token=ye,t}({});"
        replacement = (
            "t.___n=_n,t.__Nt=Nt,t.__D=D,t.__jt=jt,"
            "t.token=ye,t}({});"
        )
        if hook not in sdk_code:
            raise RuntimeError("Sentinel SDK 内部接口发生变化，无法生成 VM token")
        self._page.evaluate(
            "code => window.eval(code)", sdk_code.replace(hook, replacement)
        )
        if self._page.evaluate("typeof window.SentinelSDK") != "object":
            raise RuntimeError("Sentinel SDK 初始化失败")

    @staticmethod
    def _looks_like_vm_error(value: str) -> bool:
        try:
            decoded = base64.b64decode(value + "=" * (-len(value) % 4)).decode(
                "utf-8", errors="ignore"
            )
        except Exception:
            return False
        lowered = decoded.lower()
        return "syntaxerror" in lowered or "typeerror" in lowered or "error:" in lowered

    def vm_tokens(self, chat_req: dict, cached_proof: str) -> dict[str, str]:
        result = self._page.evaluate(
            """async ({ chatReq, cachedProof }) => {
                const sdk = window.SentinelSDK;
                sdk.__D(chatReq, cachedProof);
                const turnstile = chatReq.turnstile || {};
                const t = turnstile.dx
                    ? await sdk.___n(chatReq, turnstile.dx)
                    : null;
                let so = null;
                const observer = chatReq.so || {};
                if (observer.collector_dx && typeof sdk.__Nt === "function") {
                    so = await sdk.__Nt(observer.collector_dx);
                }
                let soFallback = null;
                if (observer.snapshot_dx && typeof sdk.__jt === "function") {
                    soFallback = await sdk.__jt(observer.snapshot_dx, cachedProof);
                }
                return { t, so, soFallback };
            }""",
            {"chatReq": chat_req, "cachedProof": cached_proof},
        )
        t_value = str((result or {}).get("t") or "")
        if (chat_req.get("turnstile", {}).get("required") and not t_value):
            raise RuntimeError("Sentinel Turnstile VM 未生成 t token")
        so_value = str((result or {}).get("so") or "")
        if so_value and self._looks_like_vm_error(so_value):
            so_value = ""
        if not so_value:
            fallback = str((result or {}).get("soFallback") or "")
            if fallback and not self._looks_like_vm_error(fallback):
                so_value = fallback
        return {"t": t_value, "so": so_value}

    def token_headers(self, flow: str) -> dict[str, str]:
        result = self._page.evaluate(
            """async flow => {
                const sdk = window.SentinelSDK;
                const token = await sdk.token(flow);
                let so = null;
                if (typeof sdk.sessionObserverToken === "function") {
                    so = await sdk.sessionObserverToken(flow);
                }
                return { token, so };
            }""",
            flow,
        )
        token = result.get("token") if isinstance(result, dict) else None
        if isinstance(token, str):
            try:
                token = json.loads(token)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Sentinel SDK 返回的 token 不是 JSON") from exc
        if not isinstance(token, dict):
            raise RuntimeError("Sentinel SDK 未返回 token")
        missing = [
            key for key in ("p", "t", "c", "id", "flow")
            if not str(token.get(key) or "")
        ]
        if missing:
            raise RuntimeError("Sentinel token 缺少字段: " + ", ".join(missing))

        headers = {
            "openai-sentinel-token": json.dumps(token, separators=(",", ":")),
        }
        so = result.get("so") if isinstance(result, dict) else None
        if isinstance(so, str):
            try:
                so = json.loads(so)
            except json.JSONDecodeError:
                so = None
        if isinstance(so, dict) and so:
            headers["openai-sentinel-so-token"] = json.dumps(
                so, separators=(",", ":")
            )
        return headers

    def close(self) -> None:
        for resource in (
            getattr(self, "_context", None),
            getattr(self, "_browser", None),
            getattr(self, "_playwright", None),
        ):
            try:
                if resource is not None:
                    resource.close()
            except Exception:
                pass


class OpenAISentinelClient:
    def __init__(
        self,
        session,
        *,
        user_agent: str,
        proxy: str | None = None,
        use_browser_runtime: bool = True,
    ):
        self.session = session
        self.user_agent = user_agent
        self.proxy = proxy
        self.use_browser_runtime = use_browser_runtime
        self._browser_runtime: _SentinelBrowserRuntime | None = None

    def build_headers(self, device_id: str, flow: str) -> dict[str, str]:
        if self.use_browser_runtime:
            generator = _SentinelTokenGenerator(self.user_agent)
            proof = generator.requirements()
            response = self.session.post(
                SENTINEL_REQ_URL,
                data=json.dumps({"p": proof, "id": device_id, "flow": flow}),
                headers={
                    "accept": "*/*",
                    "content-type": "text/plain;charset=UTF-8",
                    "origin": SENTINEL_BASE,
                    "referer": SENTINEL_FRAME_URL,
                },
            )
            chat_req = _response_json(response)
            challenge = str(chat_req.get("token") or "").strip()
            if getattr(response, "status_code", 0) >= 400 or not challenge:
                raise RuntimeError(
                    f"Sentinel challenge 获取失败: {_response_error(response, chat_req)}"
                )
            if self._browser_runtime is None:
                self._browser_runtime = _SentinelBrowserRuntime(
                    self.session,
                    user_agent=self.user_agent,
                    proxy=self.proxy,
                )
            vm = self._browser_runtime.vm_tokens(chat_req, proof)
            pow_info = chat_req.get("proofofwork") or {}
            if pow_info.get("required") and pow_info.get("seed"):
                enforcement = generator.enforcement(
                    str(pow_info.get("seed") or ""),
                    str(pow_info.get("difficulty") or "0"),
                )
            else:
                enforcement = proof
            token = {
                "p": enforcement,
                "t": vm.get("t") or "",
                "c": challenge,
                "id": device_id,
                "flow": flow,
            }
            headers = {
                "openai-sentinel-token": json.dumps(token, separators=(",", ":"))
            }
            if vm.get("so"):
                so_token = {
                    "so": vm["so"],
                    "c": challenge,
                    "id": device_id,
                    "flow": flow,
                }
                headers["openai-sentinel-so-token"] = json.dumps(
                    so_token, separators=(",", ":")
                )
            return headers
        return {"openai-sentinel-token": self._build_legacy_header(device_id, flow)}

    def build_header(self, device_id: str, flow: str) -> str:
        return self.build_headers(device_id, flow)["openai-sentinel-token"]

    def _build_legacy_header(self, device_id: str, flow: str) -> str:
        generator = _SentinelTokenGenerator(self.user_agent)
        proof = generator.requirements()
        response = self.session.post(
            SENTINEL_REQ_URL,
            data=json.dumps({"p": proof, "id": device_id, "flow": flow}),
            headers={
                "accept": "*/*",
                "content-type": "text/plain;charset=UTF-8",
                "origin": SENTINEL_BASE,
                "referer": SENTINEL_FRAME_URL,
            },
        )
        payload = _response_json(response)
        challenge = str(payload.get("token") or "").strip()
        if getattr(response, "status_code", 0) >= 400 or not challenge:
            raise RuntimeError(f"Sentinel challenge 获取失败: {_response_error(response, payload)}")
        pow_info = payload.get("proofofwork") or {}
        if pow_info.get("required") and pow_info.get("seed"):
            enforcement = generator.enforcement(
                str(pow_info.get("seed") or ""),
                str(pow_info.get("difficulty") or "0"),
            )
        else:
            enforcement = proof
        return json.dumps(
            {
                "p": enforcement,
                "t": "",
                "c": challenge,
                "id": device_id,
                "flow": flow,
            },
            separators=(",", ":"),
        )

    def close(self) -> None:
        if self._browser_runtime is not None:
            self._browser_runtime.close()
            self._browser_runtime = None


class ChatGPTProtocolRegister:
    """Synchronous worker compatible with ``ProtocolMailboxAdapter``."""

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        proxy: str | None = None,
        otp_callback: Callable[[], str] | None = None,
        log_fn: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        impersonate: str = "firefox144",
        session=None,
        sentinel_runtime: bool = True,
    ):
        self.proxy = str(proxy or "").strip() or None
        self.otp_callback = otp_callback
        self.log = log_fn or (lambda _message: None)
        self.cancel_check = cancel_check or (lambda: False)
        if session is None:
            kwargs = {"impersonate": impersonate, "timeout": 60}
            if self.proxy:
                kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
            session = requests.Session(**kwargs)
        self.session = session
        self.sentinel = OpenAISentinelClient(
            session,
            user_agent=self.user_agent,
            proxy=self.proxy,
            use_browser_runtime=sentinel_runtime,
        )
        self.device_id = str(uuid.uuid4())

    def _check_cancelled(self) -> None:
        if self.cancel_check():
            raise RuntimeError("任务已取消")

    def _common_headers(self, referer: str) -> dict:
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": OPENAI_AUTH,
            "referer": referer,
            "user-agent": self.user_agent,
        }

    def _follow_authorize_chain(self, location: str) -> None:
        current = str(location or "").strip()
        for _ in range(15):
            if not current:
                return
            self._check_cancelled()
            response = self.session.get(urljoin(OPENAI_AUTH, current), allow_redirects=False)
            current = str(response.headers.get("location") or "").strip()
        raise RuntimeError("OpenAI 授权重定向次数过多")

    def _initialize_signup(self, email: str) -> None:
        self.log("初始化 ChatGPT 协议注册会话...")
        response = self.session.get(CHATGPT_APP, allow_redirects=True)
        if getattr(response, "status_code", 0) >= 400:
            raise RuntimeError(f"ChatGPT 首页访问失败: {_response_error(response)}")
        csrf_response = self.session.get(f"{CHATGPT_APP}/api/auth/csrf")
        csrf_payload = _response_json(csrf_response)
        csrf_token = str(csrf_payload.get("csrfToken") or "").strip()
        if getattr(csrf_response, "status_code", 0) != 200 or not csrf_token:
            raise RuntimeError(f"CSRF 获取失败: {_response_error(csrf_response, csrf_payload)}")

        query = urlencode(
            {
                "prompt": "login",
                "ext-oai-did": self.device_id,
                "auth_session_logging_id": str(uuid.uuid4()),
                "screen_hint": "login_or_signup",
                "login_hint": email,
            }
        )
        signin_response = self.session.post(
            f"{CHATGPT_APP}/api/auth/signin/openai?{query}",
            data=urlencode(
                {
                    "callbackUrl": f"{CHATGPT_APP}/",
                    "csrfToken": csrf_token,
                    "json": "true",
                }
            ),
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
                "origin": CHATGPT_APP,
                "referer": f"{CHATGPT_APP}/",
                "user-agent": self.user_agent,
            },
            allow_redirects=False,
        )
        signin_payload = _response_json(signin_response)
        location = str(
            signin_payload.get("url")
            or signin_response.headers.get("location")
            or ""
        ).strip()
        if getattr(signin_response, "status_code", 0) >= 400 or not location:
            raise RuntimeError(f"OpenAI 注册授权初始化失败: {_response_error(signin_response, signin_payload)}")
        self._follow_authorize_chain(location)
        try:
            cookie_device_id = str(self.session.cookies.get("oai-did") or "").strip()
            if cookie_device_id:
                self.device_id = cookie_device_id
        except Exception:
            pass

    def _validate_otp(self, code: str) -> dict:
        response = self.session.post(
            OPENAI_API_ENDPOINTS["validate_otp"],
            json={"code": code},
            headers=self._common_headers(f"{OPENAI_AUTH}/email-verification"),
        )
        payload = _response_json(response)
        if getattr(response, "status_code", 0) >= 400 or payload.get("error"):
            raise RuntimeError(f"邮箱验证码校验失败: {_response_error(response, payload)}")
        return payload

    def _register_password(self, email: str, password: str) -> dict:
        headers = self._common_headers(f"{OPENAI_AUTH}/create-account/password")
        headers.update(self.sentinel.build_headers(
            self.device_id,
            "username_password_create",
        ))
        response = self.session.post(
            OPENAI_API_ENDPOINTS["register"],
            json={"password": password, "username": email},
            headers=headers,
        )
        payload = _response_json(response)
        if getattr(response, "status_code", 0) >= 400 or payload.get("error"):
            raise RuntimeError(f"设置 ChatGPT 密码失败: {_response_error(response, payload)}")
        return payload

    def _create_account(self, name: str, birthdate: str) -> dict:
        last_error = ""
        for attempt in range(3):
            self._check_cancelled()
            # Generate a fresh Sentinel proof for each retry.  Reusing a
            # rejected proof makes registration_disallowed retries ineffective.
            headers = self._common_headers(f"{OPENAI_AUTH}/about-you")
            headers.update(
                self.sentinel.build_headers(self.device_id, "oauth_create_account")
            )
            response = self.session.post(
                OPENAI_API_ENDPOINTS["create_account"],
                json={"name": name, "birthdate": birthdate},
                headers=headers,
            )
            payload = _response_json(response)
            if getattr(response, "status_code", 0) < 400 and not payload.get("error"):
                return payload
            last_error = _response_error(response, payload)
            if "registration_disallowed" not in last_error or attempt >= 2:
                break
            self.log(f"创建账号被临时拒绝，正在重试 ({attempt + 1}/3)...")
            time.sleep(2)
        raise RuntimeError(f"创建 ChatGPT 账号失败: {last_error}")

    def _session_result(self, email: str, password: str) -> dict:
        response = self.session.get(f"{CHATGPT_APP}/api/auth/session")
        payload = _response_json(response)
        access_token = str(payload.get("accessToken") or "").strip()
        if getattr(response, "status_code", 0) != 200 or not access_token:
            raise RuntimeError(f"注册完成但获取 ChatGPT session 失败: {_response_error(response, payload)}")
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        claims = _decode_jwt_payload(access_token)
        auth_claims = claims.get("https://api.openai.com/auth")
        if not isinstance(auth_claims, dict):
            auth_claims = {}
        account_id = str(
            auth_claims.get("chatgpt_account_id")
            or account.get("id")
            or ""
        )
        workspace_id = str(auth_claims.get("organization_id") or account_id)
        try:
            cookies = self.session.cookies.get_dict()
        except Exception:
            cookies = {}
        return {
            "email": email,
            "password": password,
            "account_id": account_id,
            "workspace_id": workspace_id,
            "access_token": access_token,
            "session_token": str(payload.get("sessionToken") or ""),
            "refresh_token": "",
            "id_token": "",
            "cookies": cookies,
            "profile": account,
            "expires_at": payload.get("expires") or "",
        }

    def run(self, *, email: str, password: str) -> dict:
        if not str(email or "").strip():
            raise RuntimeError("协议注册缺少邮箱")
        if not callable(self.otp_callback):
            raise RuntimeError("协议注册缺少 Outlook 验证码回调")
        self._check_cancelled()
        self.log(f"开始 ChatGPT 协议注册: {email}")
        try:
            self._initialize_signup(email)
            self.log("等待 Outlook 验证码...")
            code = str(self.otp_callback() or "").strip()
            if not code:
                raise RuntimeError("未收到 Outlook 验证码")
            validation = self._validate_otp(code)
            self.log("邮箱验证码校验通过")
            continue_url = str(validation.get("continue_url") or "").strip()
            if continue_url:
                self.session.get(
                    urljoin(OPENAI_AUTH, continue_url),
                    headers={
                        "referer": f"{OPENAI_AUTH}/email-verification",
                        "user-agent": self.user_agent,
                    },
                    allow_redirects=True,
                )
            if "password" in continue_url.lower():
                password_result = self._register_password(email, password)
                self.log("ChatGPT 登录密码设置成功")
                password_continue_url = str(password_result.get("continue_url") or "").strip()
                if password_continue_url:
                    self.session.get(
                        urljoin(OPENAI_AUTH, password_continue_url),
                        headers={
                            "referer": f"{OPENAI_AUTH}/create-account/password",
                            "user-agent": self.user_agent,
                        },
                        allow_redirects=True,
                    )
            name, birthdate = _random_profile()
            created = self._create_account(name, birthdate)
            self.log("ChatGPT 账号资料创建成功")
            callback_url = str(created.get("continue_url") or "").strip()
            if callback_url:
                self.session.get(
                    urljoin(OPENAI_AUTH, callback_url),
                    headers={"user-agent": self.user_agent},
                    allow_redirects=True,
                )
            result = self._session_result(email, password)
            self.log("ChatGPT 协议注册完成并已获取 session")
            return result
        finally:
            try:
                self.sentinel.close()
            except Exception:
                pass
            try:
                self.session.close()
            except Exception:
                pass
