"""Kiro 协议邮箱注册 worker。"""
from __future__ import annotations

from typing import Callable

from platforms.kiro.core import KiroRegister, _pwd, wait_for_otp


class KiroProtocolMailboxWorker:
    def __init__(self, *, proxy: str | None = None, tag: str = "KIRO", log_fn: Callable[[str], None] = print):
        self.client = KiroRegister(proxy=proxy, tag=tag)
        self.client.log = lambda msg: log_fn(msg)

    def run(
        self,
        *,
        email: str,
        password: str | None = None,
        name: str = "Kiro User",
        mail_token: str | None = None,
        otp_timeout: int = 120,
        otp_callback=None,
    ) -> dict:
        use_password = password or _pwd()
        self.client.log(f"  自动生成密码: {use_password}" if not password else f"  使用传入密码: {use_password}")
        self.client.log(f"========== 开始注册: {email} ==========")

        redir = self.client.step1_kiro_init()
        if not redir:
            raise RuntimeError("InitiateLogin failed")
        if not self.client.step2_get_wsh(redir):
            raise RuntimeError("获取wsh失败")
        if not self.client.step3_signin_flow(email):
            raise RuntimeError("signin flow失败")
        if not self.client.step4_signup_flow(email):
            raise RuntimeError("signup flow失败")
        if not self.client.profile_wf_id:
            raise RuntimeError("未获取到workflowID")
        tes = self.client.step5_get_tes_token()
        if not tes:
            self.client.log("  ⚠️ TES token获取失败, 继续...")
        if not self.client.step6_profile_load():
            raise RuntimeError("profile start失败")
        if self.client.step7_send_otp(email) is None:
            raise RuntimeError("send OTP失败")

        if otp_callback:
            self.client.log("  自动获取验证码...")
            otp = otp_callback()
        elif mail_token:
            self.client.log("  自动获取验证码...")
            otp = wait_for_otp(mail_token, timeout=otp_timeout, tag=self.client.tag)
        else:
            otp = input(f"[{self.client.tag}] 请输入验证码: ").strip()
        if not otp:
            raise RuntimeError("未获取到验证码")

        identity = self.client.step8_create_identity(otp, email, name)
        if not identity:
            raise RuntimeError("create-identity失败")
        reg_code = identity["registrationCode"]
        sign_in_state = identity["signInState"]

        signup_registration = self.client.step9_signup_registration(reg_code, sign_in_state)
        if not signup_registration:
            raise RuntimeError("signup registration失败")
        password_state = self.client.step10_set_password(use_password, email, signup_registration)
        if not password_state:
            raise RuntimeError("设置密码失败")

        login_result = self.client.step11_final_login(email, password_state)
        if not login_result:
            self.client.log("  ⚠️ 最终登录步骤失败, 但账号可能已创建成功")

        tokens = self.client.step12_get_tokens()
        if not tokens:
            self.client.log("🎉 注册完成! (但 token 获取失败, 账号可用)")
            return {"email": email, "password": use_password, "name": name}

        bearer_token = tokens["sessionToken"]
        device_tokens = self.client.step12f_device_auth(bearer_token)
        if device_tokens:
            self.client.log("🎉 注册完成! (含 accessToken + sessionToken + refreshToken)")
            return {
                "email": email,
                "password": use_password,
                "name": name,
                "accessToken": tokens["accessToken"],
                "sessionToken": tokens["sessionToken"],
                "clientId": device_tokens["clientId"],
                "clientSecret": device_tokens["clientSecret"],
                "refreshToken": device_tokens["refreshToken"],
            }

        self.client.log("🎉 注册完成! (含 accessToken + sessionToken, 但 refreshToken 获取失败)")
        return {
            "email": email,
            "password": use_password,
            "name": name,
            "accessToken": tokens["accessToken"],
            "sessionToken": tokens["sessionToken"],
        }
