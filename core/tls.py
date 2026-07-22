"""TLS 辅助工具。"""
from __future__ import annotations

import warnings
from contextlib import contextmanager
from typing import Any

from urllib3.exceptions import InsecureRequestWarning


@contextmanager
def suppress_insecure_request_warning():
    """仅在明确关闭证书校验时屏蔽 urllib3 的 TLS 告警。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureRequestWarning)
        yield


def insecure_request(request_callable, *args, **kwargs) -> Any:
    """执行 verify=False 的 requests 调用并屏蔽对应告警。"""
    kwargs.setdefault("verify", False)
    with suppress_insecure_request_warning():
        return request_callable(*args, **kwargs)


def mark_session_insecure(session: Any) -> Any:
    """
    标记 requests.Session 为 verify=False，并在调用端配合 suppress_insecure_request_warning 使用。
    返回 session 便于链式调用。
    """
    session.verify = False
    return session

