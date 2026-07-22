"""
BitBrowser local API integration.

BitBrowser（比特浏览器）暴露一个本地 HTTP API（默认 127.0.0.1:54345），
项目可以通过该 API 启动用户在 GUI 里预先配好的 profile（包含指纹、代理、
OS、UA 等），拿到 Chromium 的 CDP endpoint 之后用 Playwright
``chromium.connect_over_cdp`` 接入，就跟自己启动的 Playwright Chromium
看起来一样。

为什么不在每次任务里临时建 profile：BitBrowser 的核心价值是 profile
持久化（cookie / IndexedDB / localStorage / 浏览历史能跨任务保留），
持久化历史能让 hCaptcha 风险评分更友好。每次新建 profile 等于扔掉这个
优势，所以 V1 走"用户手动建 profile + 项目按 ID 复用"。

三种窗口模式（按反爬通过率从高到低）：
    headed  — 显示真实窗口（最像人）
    hidden  — 窗口照样渲染但移到屏幕外（占 GPU 资源跟 headed 一样，
              JS 测不出 headless tell）
    headless— 真 ``--headless=new``，性能最好，但 hCaptcha 等高强反爬
              能识别（GPU 走 SwiftShader、缺焦点事件等）

为什么不用 cffi_requests：本地 HTTP 调用不需要 TLS 反指纹，
``requests`` 标准库行为足够，依赖更轻。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urljoin

import requests


DEFAULT_BIT_API_URL = "http://127.0.0.1:54345"
"""BitBrowser 客户端默认本地 API 端口（用户自定义可在 GUI 设置里改）。"""


class BitBrowserError(RuntimeError):
    """BitBrowser 本地 API 调用失败统一抛这个；保留 ``response`` 字段方便
    业务层根据 ``msg`` 判断具体错误（比如 profile 已被占用）。"""

    def __init__(self, message: str, *, response: Optional[dict] = None):
        super().__init__(message)
        self.response = dict(response or {})


@dataclass
class BitBrowserOpenResult:
    """``/browser/open`` 返回的结构化结果。

    - ``ws_endpoint``: Playwright ``connect_over_cdp`` 接的 ws://...
    - ``http_endpoint``: 调试 HTTP 端口（``127.0.0.1:6000`` 这种）
    - ``profile_id``: 透传开起来的 profile ID
    - ``raw``: 完整响应 ``data`` 块，留给业务做 debug 日志
    """

    profile_id: str
    ws_endpoint: str
    http_endpoint: str
    raw: dict = field(default_factory=dict)


class BitBrowserClient:
    """BitBrowser 本地 API 极简客户端。

    只覆盖项目用到的 ``open`` / ``close`` 两个端点；其他端点（list /
    update / delete）按需补。设计上是无状态的：每次调用都新建 HTTP 请求，
    不维护 session（BitBrowser 本地 API 也不要 keep-alive）。
    """

    def __init__(
        self,
        api_url: str = DEFAULT_BIT_API_URL,
        *,
        api_token: str = "",
        timeout: float = 30.0,
    ):
        self._api_url = (api_url or DEFAULT_BIT_API_URL).rstrip("/") + "/"
        self._api_token = str(api_token or "").strip()
        self._timeout = float(timeout)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        # BitBrowser 企业版 / 自部署版本会要 token，社区版本不要；空字符串
        # 时不发头，避免触发严格的"非空但格式不对"校验。
        if self._api_token:
            h["X-API-Token"] = self._api_token
        return h

    def _post(self, path: str, payload: dict) -> dict:
        url = urljoin(self._api_url, path.lstrip("/"))
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise BitBrowserError(
                f"无法连接 BitBrowser 本地 API ({url})，请确认 BitBrowser "
                f"客户端已启动且 API 端口正确: {exc}"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise BitBrowserError(
                f"BitBrowser API 请求超时 ({url}, {self._timeout}s): {exc}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise BitBrowserError(f"BitBrowser API 请求失败 ({url}): {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise BitBrowserError(
                f"BitBrowser API 返回非 JSON ({url}, status={response.status_code}): "
                f"{response.text[:200]}"
            ) from exc

        # BitBrowser 返回 ``{"success": true/false, "data": {...}, "msg": "..."}``，
        # 也有版本是 ``{"code": 0, "data": {...}, "msg": ""}``。两种都识别。
        success = bool(body.get("success", body.get("code") in (0, "0")))
        if not success:
            msg = str(body.get("msg") or body.get("message") or "unknown error")
            raise BitBrowserError(
                f"BitBrowser API 失败 ({url}): {msg}", response=body
            )
        data = body.get("data")
        if not isinstance(data, dict):
            raise BitBrowserError(
                f"BitBrowser API 响应缺 data 字段 ({url}): {body}", response=body
            )
        return data

    def open(
        self,
        profile_id: str,
        *,
        args: Optional[list[str]] = None,
        load_extensions: bool = False,
        extract_ip: bool = False,
    ) -> BitBrowserOpenResult:
        """启动一个 profile，返回 CDP endpoint。

        参数：
            profile_id      用户在 BitBrowser GUI 里看到的 profile ID
                            （也叫窗口 ID / browserId，不是序号）
            args            额外 Chromium 启动 flag。本项目用来传：
                              ``--headless=new``（headless 模式）
                              ``--window-position=-32000,-32000``（hidden 模式）
            load_extensions 是否加载 profile 配置的扩展。本项目默认 False
                            来减少指纹差异；user 想要 uBlock Origin 之类
                            可以在 profile 里配，再把这个改 True。
            extract_ip      BitBrowser 启动时**额外打开一个 IP 检测标签页**
                            （默认会跳到 ``https://api.ipify.org/?format=json``）
                            用来给用户视觉确认代理生效。**本项目默认关闭**：
                              1) 业务流程要打开支付链接，多一个 ipify 标签
                                 页对用户是噪音；
                              2) profile 在 GUI 里就已经配好代理，运行期不
                                 再需要这种"检测"；
                              3) 多打开一个非业务 URL 也增加被风控关联的
                                 概率。
                            如果想恢复 BitBrowser 默认行为（IP 检测标签页），
                            实例化 ``BitBrowserContext`` 时显式 ``extract_ip=True``。
        """
        if not str(profile_id or "").strip():
            raise BitBrowserError("profile_id 不能为空")
        payload: dict = {
            "id": str(profile_id).strip(),
            "loadExtensions": bool(load_extensions),
            "extractIp": bool(extract_ip),
        }
        if args:
            # BitBrowser 期望 args 是字符串数组
            payload["args"] = [str(a) for a in args if a]
        data = self._post("browser/open", payload)
        # ws endpoint 字段名不同版本叫法不同：``ws`` / ``webSocketDebuggerUrl`` / ``wsEndpoint``
        ws_endpoint = (
            data.get("ws")
            or data.get("webSocketDebuggerUrl")
            or data.get("wsEndpoint")
            or ""
        )
        http_endpoint = (
            data.get("http")
            or data.get("debuggerAddress")
            or data.get("httpEndpoint")
            or ""
        )
        if not ws_endpoint and http_endpoint:
            # 部分版本只返 http，需要自己拼 ws。CDP 协议下 ws path 通常是
            # ``/devtools/browser/<uuid>``，要再问一下 ``/json/version``。
            ws_endpoint = self._fetch_ws_from_http(http_endpoint)
        if not ws_endpoint:
            raise BitBrowserError(
                f"BitBrowser /browser/open 未返回 ws endpoint: {data}",
                response=data,
            )
        return BitBrowserOpenResult(
            profile_id=str(profile_id).strip(),
            ws_endpoint=ws_endpoint,
            http_endpoint=http_endpoint,
            raw=data,
        )

    def close(self, profile_id: str) -> None:
        """关闭 profile（让 BitBrowser 把 Chromium 进程终止）。

        即使 BitBrowser 报"profile 不存在"，本函数也吞掉异常 —— 上层
        ``__exit__`` 关流程时不希望再抛新错盖掉真正的业务异常。"""
        try:
            self._post("browser/close", {"id": str(profile_id or "").strip()})
        except BitBrowserError:
            pass

    def _fetch_ws_from_http(self, http_endpoint: str) -> str:
        """从 ``http://127.0.0.1:6000`` 拼 ``ws://...``。

        Chromium DevTools Protocol 的标准做法：GET /json/version 拿到
        ``webSocketDebuggerUrl`` 字段，里面就有完整 ws URL。
        """
        host = http_endpoint.replace("http://", "").replace("https://", "").strip("/")
        if not host:
            return ""
        try:
            resp = requests.get(f"http://{host}/json/version", timeout=5.0)
            resp.raise_for_status()
            payload = resp.json()
            return str(payload.get("webSocketDebuggerUrl") or "")
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Context manager + Browser wrapper
# ---------------------------------------------------------------------------
#
# 核心思想：BitBrowserContext 在 ``__enter__`` 里：
#   1) 调 BitBrowser API 启动 profile
#   2) Playwright ``chromium.connect_over_cdp`` 接入
#   3) 返回一个跟 Camoufox Browser 接口兼容的 wrapper
#      （``new_page`` / ``new_context`` / ``contexts`` / ``close``）
#
# 兼容性问题：CDP attach 模式下，Playwright Browser 的 ``new_context()``
# 行为跟 launch 模式不同 —— 部分版本可以创建新 BrowserContext，但
# BitBrowser 的 profile 数据**只在默认 context 里**（cookie / localStorage
# 都跟着默认 context 走）。新建 context 等于丢掉 profile 优势。
#
# 所以 ``BitBrowserBrowserWrapper.new_context(...)`` 不真的建新 context，
# 而是返回**默认 context 的代理**，把 ``record_har_path`` 等参数尽力翻译
# 成 ``Page`` 级别的等价行为（HAR 录制目前 CDP attach 模式不支持，会 log
# 警告并跳过）。


class _BitBrowserContextProxy:
    """包默认 BrowserContext 用来兼容 Camoufox 调用的 ``new_context`` 入口。

    业务代码常见用法：
        ``ctx = browser.new_context(record_har_path=...)``
        ``page = ctx.new_page()``
        ``ctx.close()``

    BitBrowser CDP attach 下 ``record_har_path`` 没法生效（HAR 录制要
    在 launch 时附 ``--enable-net-export`` 或在 ``new_context`` 时挂）。
    没办法的事情，警告一次，page 创建照样进行。
    """

    def __init__(
        self,
        real_context,
        *,
        log: Callable[[str], None],
        record_har_path: str = "",
    ):
        self._real = real_context
        self._log = log
        self._record_har_path = record_har_path
        if record_har_path:
            log(
                "BitBrowser CDP attach 模式不支持 record_har_path，HAR "
                "录制已跳过（profile 持久化 cookie/storage 仍正常）"
            )

    def __getattr__(self, item):
        # 兜底：没显式实现的方法直接转给底层 BrowserContext
        return getattr(self._real, item)

    def new_page(self):
        return self._real.new_page()

    def close(self) -> None:
        # CDP attach 默认 context 不能关 —— 关了等于切断 BitBrowser；什么也不做。
        return None


class _BitBrowserBrowserWrapper:
    """``__enter__`` 真正返回给业务代码的对象。

    跟 Camoufox / Playwright Browser 的接口对齐：
      * ``new_page()``                 → 默认 context 里开新 page
      * ``new_context(**kwargs)``      → 返回默认 context 的 proxy
      * ``contexts``                   → 透传 Playwright contexts
      * ``close()``                    → 不直接关；由 BitBrowserContext.__exit__
                                          调 BitBrowser API close profile
    """

    def __init__(self, browser, *, log: Callable[[str], None]):
        self._browser = browser
        self._log = log

    @property
    def contexts(self):
        return self._browser.contexts

    def _default_context(self):
        ctx_list = self._browser.contexts
        if ctx_list:
            return ctx_list[0]
        # 极少数情况：BitBrowser 启动后没默认 context —— 回退到 new_context
        return self._browser.new_context()

    def new_page(self):
        return self._default_context().new_page()

    def new_context(self, **kwargs):
        record_har_path = str(kwargs.get("record_har_path") or "")
        return _BitBrowserContextProxy(
            self._default_context(),
            log=self._log,
            record_har_path=record_har_path,
        )

    def close(self) -> None:
        # 不主动调 ``self._browser.close()`` —— CDP attach 关连接会让 BitBrowser
        # 那边的 Chromium 进程仍在跑（不主动终止）。我们走 ``BitBrowserContext.__exit__``
        # 的 ``client.close(profile_id)`` 让 BitBrowser 主动结束 Chromium。
        return None


class BitBrowserContext:
    """BitBrowser 启动入口的 ``with`` 上下文管理器。

    用法跟 ``Camoufox(**launch_opts)`` 完全对齐：
        with BitBrowserContext(
            profile_id="abc123",
            api_url="http://127.0.0.1:54345",
            window_mode="hidden",
            log=print,
        ) as browser:
            page = browser.new_page()
            page.goto("https://...")

    设计要点：
      * ``__enter__`` 失败时**保证 profile 已关闭**（避免泄露 Chromium 进程）。
      * Playwright 的 ``sync_playwright()`` 跟 BitBrowser 进程独立 —— 如果
        Playwright 端连接失败，BitBrowser 那边的 profile 仍然在跑，必须
        在异常分支里调 ``client.close``。
      * 为了让"BitBrowser 没装 / 没启动"的环境仍能 import 这个模块（单测 /
        CI 经常没装 BitBrowser），Playwright import 放函数体内。
    """

    def __init__(
        self,
        *,
        profile_id: str,
        api_url: str = DEFAULT_BIT_API_URL,
        api_token: str = "",
        window_mode: str = "headed",
        extra_args: Optional[list[str]] = None,
        log: Callable[[str], None] = print,
        open_timeout: float = 30.0,
        connect_retries: int = 3,
    ):
        self._profile_id = str(profile_id or "").strip()
        if not self._profile_id:
            raise BitBrowserError(
                "BitBrowserContext 需要 profile_id（请在 BitBrowser GUI 里"
                "建好 profile 并把 ID 填入项目设置）"
            )
        normalized_mode = str(window_mode or "headed").strip().lower()
        if normalized_mode not in ("headed", "hidden", "headless"):
            raise BitBrowserError(
                f"未识别的 BitBrowser window_mode: {window_mode!r}（应为 "
                f"headed/hidden/headless 之一）"
            )
        self._window_mode = normalized_mode
        self._extra_args = list(extra_args or [])
        self._log = log
        self._open_timeout = float(open_timeout)
        self._connect_retries = max(int(connect_retries), 1)
        self._client = BitBrowserClient(
            api_url=api_url,
            api_token=api_token,
            timeout=self._open_timeout,
        )

        # 运行时状态（__enter__ 时填充）
        self._opened: Optional[BitBrowserOpenResult] = None
        self._pw_ctx = None
        self._real_browser = None
        self._wrapper: Optional[_BitBrowserBrowserWrapper] = None

    def _build_args(self) -> list[str]:
        args: list[str] = []
        if self._window_mode == "headless":
            # ``--headless=new`` 是 Chrome 109+ 的新 headless（行为接近 headed）。
            # 老 ``--headless`` 已经被反爬识别得稀烂，绝对不要用。
            args.append("--headless=new")
        elif self._window_mode == "hidden":
            # 把窗口移到屏幕外但仍真实渲染。GPU / 焦点 / 动画都正常工作，
            # 反爬测不出"我在 headless"。代价是占 GPU 资源跟 headed 一样。
            args.append("--window-position=-32000,-32000")
        # headed 模式：不加任何 flag，让 BitBrowser profile 自己的窗口大小
        # / 位置生效。
        if self._extra_args:
            args.extend(self._extra_args)
        return args

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        # 1) 调 BitBrowser API 起 profile
        self._log(
            f"BitBrowser 启动 profile {self._profile_id} "
            f"(window_mode={self._window_mode})"
        )
        open_started_at = time.monotonic()
        self._opened = self._client.open(self._profile_id, args=self._build_args())
        open_elapsed = time.monotonic() - open_started_at
        self._log(
            f"BitBrowser profile 已启动 ({open_elapsed:.1f}s): ws={self._opened.ws_endpoint[:80]}..."
            if len(self._opened.ws_endpoint) > 80
            else f"BitBrowser profile 已启动 ({open_elapsed:.1f}s): ws={self._opened.ws_endpoint}"
        )

        # 2) Playwright 接 CDP；BitBrowser 启动后偶尔会有几百毫秒的"端口已
        # 报但还没 listen"间隔，加 retry。
        try:
            pw_started_at = time.monotonic()
            self._pw_ctx = sync_playwright().start()
            self._log(f"Playwright runtime 已启动 ({time.monotonic() - pw_started_at:.1f}s)")
        except Exception:
            # Playwright 起不来 → 也得把 profile 关掉
            self._client.close(self._profile_id)
            raise

        last_exc: Optional[Exception] = None
        for attempt in range(1, self._connect_retries + 1):
            try:
                connect_started_at = time.monotonic()
                self._real_browser = self._pw_ctx.chromium.connect_over_cdp(
                    self._opened.ws_endpoint,
                    timeout=self._open_timeout * 1000,
                )
                self._log(
                    f"BitBrowser CDP 连接成功 ({time.monotonic() - connect_started_at:.1f}s, "
                    f"attempt {attempt}/{self._connect_retries})"
                )
                break
            except Exception as exc:
                connect_elapsed = time.monotonic() - connect_started_at
                last_exc = exc
                if attempt < self._connect_retries:
                    self._log(
                        f"BitBrowser CDP 连接第 {attempt}/{self._connect_retries} "
                        f"次失败 ({connect_elapsed:.1f}s)，0.5s 后重试: {exc}"
                    )
                    time.sleep(0.5)
        if self._real_browser is None:
            # 全失败：Playwright 端清场 + BitBrowser 端关 profile
            try:
                self._pw_ctx.stop()
            except Exception:
                pass
            self._pw_ctx = None
            self._client.close(self._profile_id)
            raise BitBrowserError(
                f"BitBrowser CDP 连接失败（{self._connect_retries} 次都没成功）: {last_exc}"
            )

        self._wrapper = _BitBrowserBrowserWrapper(self._real_browser, log=self._log)
        return self._wrapper

    def __exit__(self, exc_type, exc, tb):
        # 顺序：Playwright 端断 CDP → BitBrowser 端关 profile → 停 Playwright。
        # 单步异常都吞掉，保证清理跑完，不要给真正的业务异常盖锅。
        try:
            if self._real_browser is not None:
                self._real_browser.close()
        except Exception:
            pass
        try:
            if self._pw_ctx is not None:
                self._pw_ctx.stop()
        except Exception:
            pass
        try:
            self._client.close(self._profile_id)
        except Exception:
            pass
        self._real_browser = None
        self._pw_ctx = None
        self._wrapper = None
        self._opened = None
        return False
