"""Manual captcha solver — blocks waiting for human input."""
from core.base_captcha import BaseCaptcha
from providers.registry import register_provider


@register_provider("captcha", "manual")
class ManualCaptcha(BaseCaptcha):
    """人工打码，阻塞等待用户输入"""

    @classmethod
    def from_config(cls, config: dict) -> 'ManualCaptcha':
        return cls()

    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        return input(f"请手动获取 Turnstile token ({page_url}): ").strip()

    def solve_image(self, image_b64: str) -> str:
        return input("请输入图片验证码: ").strip()
