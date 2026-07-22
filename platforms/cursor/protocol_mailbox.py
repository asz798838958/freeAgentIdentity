"""Cursor 协议邮箱注册 worker。"""
from __future__ import annotations

from typing import Callable, Optional

from platforms.cursor.core import CursorRegister, _rand_password


class CursorProtocolMailboxWorker:
    def __init__(self, *, proxy: str | None = None, log_fn: Callable[[str], None] = print):
        self.client = CursorRegister(proxy=proxy, log_fn=log_fn)
        self.log = log_fn

    def run(
        self,
        *,
        email: str,
        password: str | None = None,
        otp_callback: Optional[Callable[[], str]] = None,
        captcha_solver=None,
    ) -> dict:
        use_password = password or _rand_password()
        self.log(f"邮箱: {email}")
        self.log("Step1: 获取 session...")
        state_encoded, _ = self.client.step1_get_session()
        self.log("Step2: 提交邮箱...")
        self.client.step2_submit_email(email, state_encoded)
        self.log("Step3: 提交密码 + Turnstile...")
        self.client.step3_submit_password(use_password, email, state_encoded, captcha_solver)
        self.log("等待 OTP 邮件...")
        otp = otp_callback() if otp_callback else input("OTP: ")
        if not otp:
            raise RuntimeError("未获取到验证码")
        self.log(f"验证码: {otp}")
        self.log("Step4: 提交 OTP...")
        auth_code = self.client.step4_submit_otp(otp, email, state_encoded)
        self.log("Step5: 获取 Token...")
        token = self.client.step5_get_token(auth_code, state_encoded)
        return {"email": email, "password": use_password, "token": token}
