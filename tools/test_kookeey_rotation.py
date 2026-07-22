"""测试 kookeey rotating gateway 是否每次新连接给新 IP。

测试 3 个场景：
1. 默认 curl_cffi session（带 keep-alive）—— 看是否所有请求同 IP
2. 加 FORBID_REUSE+FRESH_CONNECT —— 看是否每次新 IP
3. 多次重建 session —— 对照组
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from curl_cffi import requests, CurlOpt
from sqlmodel import Session, select
from core.db import ProxyModel, engine

# 拿 kookeey 代理 URL
with Session(engine) as s:
    proxies = s.exec(select(ProxyModel).where(ProxyModel.is_active == True)).all()
    if not proxies:
        print("ERROR: 数据库无可用代理")
        sys.exit(1)
    proxy_url = proxies[0].url

import re as _re
print(f"使用代理: {_re.sub(r'(://)([^:]+):([^@]+)@', r'\\1***:***@', proxy_url)}")
print()

# 场景 1: 默认 session
print("=== 场景 1: 默认 curl_cffi session（keep-alive）===")
sess = requests.Session(impersonate="firefox135", proxy=proxy_url)
for i in range(4):
    try:
        r = sess.get("https://api.ipify.org?format=json", timeout=15)
        print(f"  请求 {i+1}: IP = {r.json().get('ip')}")
    except Exception as e:
        print(f"  请求 {i+1}: 失败 {e}")

print()
print("=== 场景 2: setopt FORBID_REUSE + FRESH_CONNECT ===")
sess2 = requests.Session(impersonate="firefox135", proxy=proxy_url)
try:
    sess2.curl.setopt(CurlOpt.FORBID_REUSE, 1)
    sess2.curl.setopt(CurlOpt.FRESH_CONNECT, 1)
    print("  setopt 成功")
except Exception as e:
    print(f"  setopt 失败: {e}")

for i in range(4):
    try:
        r = sess2.get("https://api.ipify.org?format=json", timeout=15)
        print(f"  请求 {i+1}: IP = {r.json().get('ip')}")
    except Exception as e:
        print(f"  请求 {i+1}: 失败 {e}")

print()
print("=== 场景 3: 每次重建 session（基准对照）===")
for i in range(4):
    try:
        s = requests.Session(impersonate="firefox135", proxy=proxy_url)
        r = s.get("https://api.ipify.org?format=json", timeout=15)
        print(f"  请求 {i+1}: IP = {r.json().get('ip')}")
    except Exception as e:
        print(f"  请求 {i+1}: 失败 {e}")
