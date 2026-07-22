from __future__ import annotations


class RegistrationError(RuntimeError):
    """注册流程基础异常。"""


class IdentityResolutionError(RegistrationError):
    """身份解析失败。"""


class CaptchaConfigurationError(RegistrationError):
    """验证码配置不可用。"""


class OtpTimeoutError(RegistrationError):
    """验证码等待超时。"""


class BrowserReuseRequiredError(RegistrationError):
    """无头 OAuth 缺少可复用浏览器会话。"""


class RegistrationUnsupportedError(RegistrationError):
    """当前平台或执行器不支持该注册路径。"""

