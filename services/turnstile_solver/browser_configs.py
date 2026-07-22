import random

class browser_config:
    @staticmethod
    def get_random_browser_config(browser_type):
        # 返回: 浏览器名, 版本, User-Agent, Sec-CH-UA
        versions = ["135.0.0.0", "136.0.0.0", "137.0.0.0"]
        ver = random.choice(versions)
        major = ver.split(".")[0]
        ua = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36"
        )
        sec_ch_ua = f'"Google Chrome";v="{major}", "Not-A.Brand";v="8", "Chromium";v="{major}"'
        return "chrome", ver, ua, sec_ch_ua

    @staticmethod
    def get_browser_config(name, version):
        major = str(version).split(".")[0]
        ua = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
        )
        sec_ch_ua = f'"Google Chrome";v="{major}", "Not-A.Brand";v="8", "Chromium";v="{major}"'
        return ua, sec_ch_ua