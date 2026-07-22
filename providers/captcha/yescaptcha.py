"""YesCaptcha — cloud Turnstile solver."""
import time

import requests

from core.base_captcha import BaseCaptcha
from core.tls import insecure_request
from providers.registry import register_provider


class PermanentCaptchaError(RuntimeError):
    """**本轮 challenge** 内不可恢复的求解错误。

    捕获到这个异常的调用方应立刻停止针对当前 sitekey 的自动重试，把控制权
    交还给上层（manual wait / 整体放弃）。常见触发：

    - ``ERROR_DOMAIN_NOT_ALLOWED``  - YesCaptcha 后端没给该 sitekey 开白名单
    - ``ERROR_KEY_DOES_NOT_EXIST``  - sitekey 抠错
    - ``ERROR_ZERO_BALANCE``         - 账户余额耗尽
    - ``ERROR_IP_BLOCKED_*``         - 客户端 IP 被风控（继续重试只会越拖越久）

    属性 ``error_code`` 暴露原始 errorCode 便于日志诊断。
    """

    def __init__(self, message: str, *, error_code: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code


# **PayPal 实战证据** task_1779728842876：sitekey ``bf07db68-...`` 在 YesCaptcha
# 上没白名单，3s 一次的 retry loop 立刻把帐号刷出 ``ERROR_IP_BLOCKED_5MIN``。
# 必须 fail-fast 让上层降级到 manual wait，不要继续浪费 quota / 招封禁。
_PERMANENT_ERROR_CODES: frozenset = frozenset({
    "ERROR_DOMAIN_NOT_ALLOWED",
    "ERROR_KEY_DOES_NOT_EXIST",
    "ERROR_ZERO_BALANCE",
    "ERROR_IP_BLOCKED",
    "ERROR_IP_BLOCKED_5MIN",
    "ERROR_IP_BLOCKED_10MIN",
    "ERROR_IP_BLOCKED_60MIN",
    "ERROR_ACCOUNT_SUSPENDED",
    "ERROR_TASK_NOT_SUPPORTED",
})


def _is_permanent_error_code(code) -> bool:
    if not code:
        return False
    code_upper = str(code).strip().upper()
    if code_upper in _PERMANENT_ERROR_CODES:
        return True
    return any(code_upper.startswith(prefix) for prefix in ("ERROR_IP_BLOCKED", "ERROR_ACCOUNT_"))


@register_provider("captcha", "yescaptcha_api")
class YesCaptcha(BaseCaptcha):
    def __init__(self, client_key: str):
        self.client_key = client_key
        self.api = "https://api.yescaptcha.com"

    @classmethod
    def from_config(cls, config: dict) -> 'YesCaptcha':
        client_key = str(config.get("yescaptcha_key", "") or "")
        if not client_key:
            raise RuntimeError("YesCaptcha Key 未配置")
        return cls(client_key)

    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        r = insecure_request(requests.post, f"{self.api}/createTask", json={
            "clientKey": self.client_key,
            "task": {"type": "TurnstileTaskProxyless",
                     "websiteURL": page_url, "websiteKey": site_key}
        }, timeout=30)
        task_id = r.json().get("taskId")
        if not task_id:
            raise RuntimeError(f"YesCaptcha 创建任务失败: {r.text}")
        for _ in range(60):
            time.sleep(3)
            d = insecure_request(requests.post, f"{self.api}/getTaskResult", json={
                "clientKey": self.client_key, "taskId": task_id
            }, timeout=30).json()
            if d.get("status") == "ready":
                return d["solution"]["token"]
            if d.get("errorId", 0) != 0:
                raise RuntimeError(f"YesCaptcha 错误: {d}")
        raise TimeoutError("YesCaptcha Turnstile 超时")

    def solve_recaptcha_v2(self, page_url: str, site_key: str) -> str:
        r = insecure_request(requests.post, f"{self.api}/createTask", json={
            "clientKey": self.client_key,
            "task": {"type": "RecaptchaV2TaskProxyless",
                     "websiteURL": page_url, "websiteKey": site_key}
        }, timeout=30)
        task_id = r.json().get("taskId")
        if not task_id:
            raise RuntimeError(f"YesCaptcha 创建 reCAPTCHA 任务失败: {r.text}")
        for _ in range(60):
            time.sleep(3)
            d = insecure_request(requests.post, f"{self.api}/getTaskResult", json={
                "clientKey": self.client_key, "taskId": task_id
            }, timeout=30).json()
            if d.get("status") == "ready":
                solution = d.get("solution") or {}
                token = solution.get("gRecaptchaResponse") or solution.get("token") or solution.get("response")
                if token:
                    return str(token)
                raise RuntimeError(f"YesCaptcha reCAPTCHA 返回结果缺少 token: {d}")
            if d.get("errorId", 0) != 0:
                raise RuntimeError(f"YesCaptcha reCAPTCHA 错误: {d}")
        raise TimeoutError("YesCaptcha reCAPTCHA 超时")

    def solve_hcaptcha(self, page_url: str, site_key: str) -> str:
        """求解 hCaptcha (proxyless)。

        **PayPal 实战证据** (`@tools/captures/checkout-20260526-003842-z6qrov0qi0_edu.hsxhome.com.har`
        entry 347): ``paypal.com/pay/?...`` Security Challenge 页面嵌的
        iframe ``paypalobjects.com/.../hcaptcha/hcaptcha_fph.html?siteKey=...``
        指向自定义域 ``hcaptcha.paypal.com`` —— 这是 **enterprise hCaptcha**，
        不是普通 hCaptcha。

        YesCaptcha 普通 ``HCaptchaTaskProxyless`` 对 enterprise sitekey 会返
        ``ERROR_DOMAIN_NOT_ALLOWED``（实战 task_1779728405206 的失败 log 证据）。
        必须先用 ``HCaptchaEnterpriseTaskProxyless`` 试一次；它对部分非 enterprise
        sitekey 也兼容（YesCaptcha 内部会按 sitekey 形态 fallback）。

        失败回退到普通 ``HCaptchaTaskProxyless`` 兼容老 sitekey。两种都不行才抛错。
        """
        last_error = ""
        last_perm_code = ""
        for task_type in ("HCaptchaEnterpriseTaskProxyless", "HCaptchaTaskProxyless"):
            try:
                token = self._submit_hcaptcha_task(task_type, page_url, site_key)
                if token:
                    return token
            except PermanentCaptchaError as exc:
                # ``ERROR_IP_BLOCKED_*`` / ``ERROR_ZERO_BALANCE`` 此时 fallback 到第二个
                # task_type 也只会再撞同样的封禁——直接抛出去，让上层 fail-fast 不要再重试。
                last_perm_code = exc.error_code or last_perm_code
                last_error = f"[{task_type}] {exc}"
                if exc.error_code and any(
                    exc.error_code.upper().startswith(prefix)
                    for prefix in ("ERROR_IP_BLOCKED", "ERROR_ACCOUNT_", "ERROR_ZERO_BALANCE")
                ):
                    raise PermanentCaptchaError(
                        f"YesCaptcha hCaptcha 永久错误（{exc.error_code}），停止本轮自动重试: {last_error}",
                        error_code=exc.error_code,
                    ) from exc
                # ERROR_DOMAIN_NOT_ALLOWED / ERROR_KEY_DOES_NOT_EXIST 在第一种 task_type 下
                # 出现时换 enterprise/basic 再试一次有意义，继续 fallback。
                continue
            except RuntimeError as exc:
                last_error = f"[{task_type}] {exc}"
                continue
        if last_perm_code:
            raise PermanentCaptchaError(
                f"YesCaptcha hCaptcha 永久错误（{last_perm_code}），enterprise+basic 都失败: {last_error}",
                error_code=last_perm_code,
            )
        raise RuntimeError(f"YesCaptcha hCaptcha 创建任务失败（已尝试 enterprise + basic）: {last_error}")

    def _submit_hcaptcha_task(self, task_type: str, page_url: str, site_key: str) -> str:
        """单次 hCaptcha 任务提交 + 轮询 helper。

        ``task_type`` 取 ``HCaptchaTaskProxyless`` 或 ``HCaptchaEnterpriseTaskProxyless``。
        创建任务返 errorId != 0 / 无 taskId 直接抛 RuntimeError，让上层 fallback。
        """
        r = insecure_request(requests.post, f"{self.api}/createTask", json={
            "clientKey": self.client_key,
            "task": {"type": task_type,
                     "websiteURL": page_url, "websiteKey": site_key}
        }, timeout=30)
        body = r.json()
        if body.get("errorId", 0) != 0:
            err_code = str(body.get("errorCode") or "")
            err_desc = str(body.get("errorDescription") or "")
            msg = f"创建任务失败: errorCode={err_code!r} errorDescription={err_desc!r}"
            if _is_permanent_error_code(err_code):
                raise PermanentCaptchaError(msg, error_code=err_code)
            raise RuntimeError(msg)
        task_id = body.get("taskId")
        if not task_id:
            raise RuntimeError(f"创建任务失败: 无 taskId, body={body}")
        for _ in range(60):
            time.sleep(3)
            d = insecure_request(requests.post, f"{self.api}/getTaskResult", json={
                "clientKey": self.client_key, "taskId": task_id
            }, timeout=30).json()
            if d.get("status") == "ready":
                solution = d.get("solution") or {}
                token = (
                    solution.get("gRecaptchaResponse")
                    or solution.get("token")
                    or solution.get("response")
                )
                if token:
                    return str(token)
                raise RuntimeError(f"返回结果缺少 token: {d}")
            if d.get("errorId", 0) != 0:
                err_code = str(d.get("errorCode") or "")
                err_desc = str(d.get("errorDescription") or "")
                msg = f"task 错误: errorCode={err_code!r} errorDescription={err_desc!r}"
                if _is_permanent_error_code(err_code):
                    raise PermanentCaptchaError(msg, error_code=err_code)
                raise RuntimeError(msg)
        raise TimeoutError(f"{task_type} 求解超时")

    def solve_image(self, image_b64: str) -> str:
        raise NotImplementedError
