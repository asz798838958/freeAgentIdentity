"""执行器基类 - 抽象 HTTP 请求层，支持 protocol/headless/headed 三种模式"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Response:
    status_code: int
    text: str
    headers: dict = field(default_factory=dict)
    cookies: dict = field(default_factory=dict)

    def json(self) -> Any:
        import json
        return json.loads(self.text)


class BaseExecutor(ABC):
    def __init__(self, proxy: str = None):
        self.proxy = proxy

    @abstractmethod
    def get(self, url: str, *, headers: dict = None, params: dict = None) -> Response:
        ...

    @abstractmethod
    def post(self, url: str, *, headers: dict = None, params: dict = None,
             data: dict = None, json: Any = None) -> Response:
        ...

    @abstractmethod
    def get_cookies(self) -> dict:
        ...

    @abstractmethod
    def set_cookies(self, cookies: dict) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
