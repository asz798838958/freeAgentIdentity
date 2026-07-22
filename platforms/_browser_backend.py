"""
浏览器后端抽象层 —— 让上层业务代码（chatgpt 注册 / payment.py）能在
Camoufox 和 BitBrowser 两套实现之间无差别切换。

设计目标：
    1) **零侵入式开关**：调用方传一个 ``BrowserBackendConfig``，dispatcher
       自己决定调 ``Camoufox(**launch_opts)`` 还是 ``BitBrowserContext(...)``，
       上层用 ``with`` 拿到的 browser 对象接口一致。
    2) **延迟 import**：BitBrowser 模块只在真用 BitBrowser 时才 import（避免
       社区版用户因为没装比特浏览器而跑不起来）。
    3) **checkout_mode 字符串集中解析**：UI 那边塞过来的字符串
       （``camoufox_headed`` / ``camoufox_headless`` / ``bitbrowser_headed`` /
       ``bitbrowser_hidden`` / ``bitbrowser_headless``）都在这一处映射到
       ``BrowserBackendConfig``，避免到处 ``if mode == "..."``。

为什么不直接在每个调用点写分支：
    PayPal checkout 主流程已经有 100+ 行的 launch_opts 构造 + Camoufox
    特有的指纹 dedup / record_har / cookies 注入。BitBrowser 路径下这些
    要么不需要（profile 已带指纹）要么不支持（CDP attach 不能 record_har）。
    塞 5 处 ``if backend == ...`` 既乱又难测。集中到一个 dispatcher 里，
    每个分支独立 monkeypatch 单测。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ._bitbrowser import (  # noqa: F401  -- re-export for convenience
    DEFAULT_BIT_API_URL,
    BitBrowserContext,
    BitBrowserError,
)


VALID_BACKENDS = ("camoufox", "bitbrowser")
"""项目支持的两种 browser backend。protocol 模式不走浏览器，不在这里处理。"""

VALID_WINDOW_MODES = ("headed", "hidden", "headless")
"""三种窗口形态。``hidden`` 仅 BitBrowser 支持；Camoufox 走时被映射成
``headed``（Camoufox 不支持移屏外显示，强行 hidden 没意义）。"""


@dataclass
class BrowserBackendConfig:
    """browser backend 启动配置 —— 跨调用点的统一入参。

    业务调用方按以下三种方式之一构造：
        1) ``BrowserBackendConfig.camoufox(headless=False)``
        2) ``BrowserBackendConfig.bitbrowser(profile_id="abc", window_mode="hidden")``
        3) ``parse_checkout_mode("bitbrowser_hidden", bit_profile_id="abc")``
    """

    backend: str = "camoufox"
    window_mode: str = "headed"  # headed / hidden / headless
    # BitBrowser 专用字段；camoufox 路径下被忽略。
    bit_profile_id: str = ""
    bit_api_url: str = DEFAULT_BIT_API_URL
    bit_api_token: str = ""

    def __post_init__(self) -> None:
        if self.backend not in VALID_BACKENDS:
            raise ValueError(
                f"未识别的 backend: {self.backend!r}（应为 {VALID_BACKENDS} 之一）"
            )
        if self.window_mode not in VALID_WINDOW_MODES:
            raise ValueError(
                f"未识别的 window_mode: {self.window_mode!r}"
                f"（应为 {VALID_WINDOW_MODES} 之一）"
            )
        # Camoufox 没有 hidden 模式概念（Firefox 没法直接 ``--window-position``
        # 移到屏幕外又保留正常渲染），强行 hidden 等同 headed，告知调用方。
        if self.backend == "camoufox" and self.window_mode == "hidden":
            self.window_mode = "headed"
        # BitBrowser 必须有 profile_id
        if self.backend == "bitbrowser" and not str(self.bit_profile_id or "").strip():
            raise ValueError(
                "BitBrowser backend 必须提供 bit_profile_id（在 BitBrowser GUI "
                "里建 profile 后把 ID 填到项目设置）"
            )

    @classmethod
    def camoufox(cls, *, headless: bool = False) -> "BrowserBackendConfig":
        return cls(backend="camoufox", window_mode="headless" if headless else "headed")

    @classmethod
    def bitbrowser(
        cls,
        *,
        profile_id: str,
        window_mode: str = "headed",
        api_url: str = DEFAULT_BIT_API_URL,
        api_token: str = "",
    ) -> "BrowserBackendConfig":
        return cls(
            backend="bitbrowser",
            window_mode=window_mode,
            bit_profile_id=profile_id,
            bit_api_url=api_url,
            bit_api_token=api_token,
        )

    @property
    def is_headless(self) -> bool:
        """业务代码用来设 launch_opts['headless'] / 决定保留浏览器秒数。

        ``hidden`` 模式从用户体验看是"看不到窗口"，但底层 Chromium 不是
        headless（页面真在跑）—— 业务代码该当 headed 处理（保留窗口、
        允许人手 fallback 等行为）。
        """
        return self.window_mode == "headless"

    @property
    def is_camoufox(self) -> bool:
        return self.backend == "camoufox"

    @property
    def is_bitbrowser(self) -> bool:
        return self.backend == "bitbrowser"


def parse_checkout_mode(
    mode: str,
    *,
    bit_profile_id: str = "",
    bit_api_url: str = "",
    bit_api_token: str = "",
) -> BrowserBackendConfig:
    """把 UI 传过来的字符串 ``checkout_mode`` 解析成 ``BrowserBackendConfig``。

    支持的字符串（UI dropdown 选项就是这几个）：
        camoufox_headed       Camoufox 前台
        camoufox_headless     Camoufox headless
        bitbrowser_headed     BitBrowser 前台
        bitbrowser_hidden     BitBrowser 隐藏窗口（推荐 PayPal 用）
        bitbrowser_headless   BitBrowser headless（最快但反爬识别率高）

    未识别的字符串回落到 ``camoufox_headed``（最保守、最常用的默认）。
    ``protocol`` 模式不走这条路 —— payment.py 里已经先判 protocol 单独
    分发了，根本不会调到这里。
    """
    normalized = str(mode or "").strip().lower()

    # 未显式传 bit_api_url 时，优先读 BIT_API_URL 环境变量，再回退默认值
    if not bit_api_url:
        bit_api_url = os.environ.get("BIT_API_URL", "").strip() or DEFAULT_BIT_API_URL
    if not bit_api_token:
        bit_api_token = os.environ.get("BIT_API_TOKEN", "").strip()

    if normalized == "bitbrowser_headed":
        return BrowserBackendConfig.bitbrowser(
            profile_id=bit_profile_id,
            window_mode="headed",
            api_url=bit_api_url,
            api_token=bit_api_token,
        )
    if normalized == "bitbrowser_hidden":
        return BrowserBackendConfig.bitbrowser(
            profile_id=bit_profile_id,
            window_mode="hidden",
            api_url=bit_api_url,
            api_token=bit_api_token,
        )
    if normalized == "bitbrowser_headless":
        return BrowserBackendConfig.bitbrowser(
            profile_id=bit_profile_id,
            window_mode="headless",
            api_url=bit_api_url,
            api_token=bit_api_token,
        )
    if normalized == "camoufox_headless":
        return BrowserBackendConfig.camoufox(headless=True)
    # 默认：camoufox_headed（包括 ``camoufox_headed`` / 空字符串 / 未识别）
    return BrowserBackendConfig.camoufox(headless=False)


def open_browser_backend(
    *,
    launch_opts: dict,
    config: BrowserBackendConfig,
    camoufox_class: Optional[Any],
    log: Callable[[str], None] = print,
):
    """统一启动入口 —— 按 ``config.backend`` 分发。返回的对象可以直接
    用在 ``with`` 语句里，``__enter__`` 返回 Camoufox 风格的 browser。

    参数：
        launch_opts     Camoufox 的 launch_opts dict（headless / proxy /
                        block_webrtc / locale / os 等）。BitBrowser 路径
                        下大部分字段被忽略（profile 已经定好了），只看
                        ``window_mode``（也是从 ``config`` 来的）。
        config          BrowserBackendConfig 实例
        camoufox_class  Camoufox 类（``camoufox.sync_api.Camoufox``）。
                        如果 ``config.is_camoufox`` 但这里传 None，抛
                        RuntimeError。这里取参数注入是为了让调用方
                        显式管理 Camoufox 是否可用，避免 dispatcher 模块
                        再 import 一次。
        log             状态日志回调。BitBrowser 路径会输出 profile
                        启动 / CDP 连接进度。

    返回：
        context manager（Camoufox 实例 或 BitBrowserContext 实例）

    抛出：
        RuntimeError    Camoufox 路径但 ``camoufox_class`` 是 None
        BitBrowserError BitBrowser API 失败 / profile 启动失败
        ValueError      配置非法（在 BrowserBackendConfig 构造时就抛了）
    """
    if config.is_bitbrowser:
        return BitBrowserContext(
            profile_id=config.bit_profile_id,
            api_url=config.bit_api_url,
            api_token=config.bit_api_token,
            window_mode=config.window_mode,
            log=log,
        )

    # camoufox 路径
    if camoufox_class is None:
        raise RuntimeError(
            "Camoufox 不可用，请先安装并执行 python -m camoufox fetch"
        )
    return camoufox_class(**launch_opts)
