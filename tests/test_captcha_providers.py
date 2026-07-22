from types import SimpleNamespace

from providers.captcha import yescaptcha as yescaptcha_module
from providers.captcha.yescaptcha import YesCaptcha


class _Response:
    def __init__(self, data: dict, text: str = ""):
        self._data = data
        self.text = text or str(data)

    def json(self):
        return self._data


def test_yescaptcha_solves_recaptcha_v2_with_proxyless_task(monkeypatch):
    calls = []
    responses = [
        _Response({"taskId": "task-123"}),
        _Response({"status": "processing"}),
        _Response({"status": "ready", "solution": {"gRecaptchaResponse": "recaptcha-token"}}),
    ]

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(yescaptcha_module, "insecure_request", fake_request)
    monkeypatch.setattr(yescaptcha_module, "time", SimpleNamespace(sleep=lambda seconds: None), raising=False)

    solver = YesCaptcha("client-key")

    assert solver.solve_recaptcha_v2("https://paypal.test/signup", "site-key") == "recaptcha-token"
    assert calls[0][2]["json"] == {
        "clientKey": "client-key",
        "task": {
            "type": "RecaptchaV2TaskProxyless",
            "websiteURL": "https://paypal.test/signup",
            "websiteKey": "site-key",
        },
    }
