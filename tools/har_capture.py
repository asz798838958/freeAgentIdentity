"""
自动 HAR 抓包工具 — 打开浏览器录制用户操作，保存 HAR 文件。

用法:
    # 打开浏览器，手动注册，关闭后自动保存 HAR
    python3 tools/har_capture.py --url https://auth.example.com/signup --name example

    # 带代理
    python3 tools/har_capture.py --url https://auth.example.com/signup --name example --proxy http://127.0.0.1:7890

输出:
    tools/captures/example.har
"""
from __future__ import annotations

import argparse
import os
import sys


CAPTURE_DIR = os.path.join(os.path.dirname(__file__), "captures")


def capture_har(url: str, name: str, proxy: str = None, headless: bool = False):
    from playwright.sync_api import sync_playwright

    os.makedirs(CAPTURE_DIR, exist_ok=True)
    har_path = os.path.join(CAPTURE_DIR, f"{name}.har")

    print(f"启动浏览器...")
    print(f"  目标: {url}")
    print(f"  HAR: {har_path}")
    if proxy:
        print(f"  代理: {proxy}")
    print(f"\n请在浏览器中完成注册/登录流程，完成后关闭浏览器窗口。\n")

    with sync_playwright() as p:
        launch_args = {"headless": headless}
        if proxy:
            launch_args["proxy"] = {"server": proxy}

        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(
            record_har_path=har_path,
            record_har_url_filter="**/*",
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        # 等待用户关闭浏览器
        try:
            page.wait_for_event("close", timeout=600_000)  # 10 分钟超时
        except Exception:
            pass

        context.close()
        browser.close()

    size = os.path.getsize(har_path) if os.path.exists(har_path) else 0
    print(f"\n✓ HAR 已保存: {har_path} ({size / 1024:.0f} KB)")
    print(f"\n下一步: python3 tools/har_analyze.py --file {har_path}")
    return har_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HAR 抓包工具")
    parser.add_argument("--url", required=True, help="目标 URL")
    parser.add_argument("--name", required=True, help="站点名称（用于文件名）")
    parser.add_argument("--proxy", help="代理 URL")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    args = parser.parse_args()
    capture_har(args.url, args.name, proxy=args.proxy, headless=args.headless)
