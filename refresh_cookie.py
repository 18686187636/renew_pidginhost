#!/usr/bin/env python3
"""在 GitHub Actions 里启动 Chrome，等用户通过 noVNC 手动完成 GitHub OAuth 登录 PidginHost，
然后把 pidginhost.com 的 session cookies 导出并写回 GitHub Secret PANEL_COOKIE。"""

from __future__ import annotations

import base64
import os
import sys
import time

import requests
from nacl import encoding, public

from DrissionPage import ChromiumOptions, ChromiumPage

LOGIN_URL = "https://www.pidginhost.com/panel/login/"
PANEL_HOST = "www.pidginhost.com"
WAIT_TIMEOUT = 25 * 60  # 25 分钟


def _all_cookies(page: ChromiumPage) -> list[dict]:
    try:
        result = page.cookies(all_domains=True)
        if result:
            return result
    except TypeError:
        pass
    except Exception as exc:
        print(f"[setup] cookies(all_domains=True) 失败: {exc}")

    try:
        return page.cookies() or []
    except Exception as exc:
        print(f"[setup] cookies() 失败: {exc}")
        return []


def _is_logged_in(url: str) -> bool:
    if not url:
        return False
    if PANEL_HOST not in url:
        return False
    if "github.com" in url:
        return False
    if "/login" in url or "/signup" in url or "/oauth" in url:
        return False
    return "/panel/" in url


def main() -> int:
    co = ChromiumOptions()
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-infobars")
    co.set_argument("--lang=zh-CN,zh;q=0.9,en;q=0.8")
    co.set_argument("--window-size=1280,800")
    co.set_argument("--disable-blink-features=AutomationControlled")

    co.headless(False)

    proxy = os.environ.get("PROXY_SERVER", "").strip()
    if proxy:
        print(f"[setup] 使用代理: {proxy}")
        try:
            co.set_proxy(proxy)
        except Exception as exc:
            print(f"[setup] 设置代理失败: {exc}")

    for path in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
        if os.path.exists(path):
            co.set_browser_path(path)
            print(f"[setup] 使用 Chrome: {path}")
            break

    co.auto_port()

    page = ChromiumPage(co)
    page.get(LOGIN_URL)

    print("=" * 60)
    print("Chrome 已启动并打开 PidginHost 登录页")
    print("请在 noVNC 里点击 'Sign in with GitHub'，完成 GitHub 登录 + 2FA + OAuth 授权")
    print("=" * 60)

    deadline = time.time() + WAIT_TIMEOUT
    last_url = ""
    while time.time() < deadline:
        try:
            url = page.url
        except Exception:
            url = ""

        if url and url != last_url:
            print(f"[setup] URL: {url}")
            last_url = url

        if _is_logged_in(url):
            print("[setup] 检测到已进入 PidginHost 面板，等待 5 秒让 session 稳定...")
            time.sleep(5)
            return _export_and_save(page)

        time.sleep(2)

    print("[setup] 超时未完成，退出")
    return 1


def _export_and_save(page: ChromiumPage) -> int:
    all_cookies = _all_cookies(page)
    print(f"[setup] 读取到全部 cookie: {len(all_cookies)} 条")

    ph_cookies = [
        c for c in all_cookies
        if "pidginhost.com" in str(c.get("domain") or "").lower()
    ]

    print(f"[setup] pidginhost.com 域 cookie: {len(ph_cookies)} 条")
    for c in ph_cookies:
        print(f"[setup]   {c.get('name')} (domain={c.get('domain')})")

    wanted = {}
    for c in ph_cookies:
        name = c.get("name")
        if name in ("sessionid", "csrftoken"):
            wanted[name] = c.get("value", "")

    if "sessionid" not in wanted:
        print("[setup] 错误：没有找到 sessionid，无法导出")
        for c in all_cookies:
            print(f"[setup]   domain={c.get('domain')} name={c.get('name')}")
        return 1

    cookie_str = "; ".join(f"{k}={v}" for k, v in wanted.items())
    print(f"[setup] PANEL_COOKIE 长度: {len(cookie_str)}")

    _update_secret("PANEL_COOKIE", cookie_str)
    return 0


def _update_secret(name: str, value: str) -> None:
    token = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()

    if not token or not repo:
        print("=" * 60)
        print("[setup] 未配置 GH_PAT 或 GITHUB_REPOSITORY，无法自动写回 Secret。")
        print("[setup] 请手动复制下面这段到 Secret " + name)
        print("=" * 60)
        print(value)
        print("=" * 60)
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers,
        timeout=20,
    )
    r.raise_for_status()
    key_data = r.json()

    pk = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pk)
    encrypted = sealed.encrypt(value.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    r = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]},
        timeout=20,
    )
    r.raise_for_status()
    print(f"[setup] ✅ Secret {name} 已自动更新")


if __name__ == "__main__":
    sys.exit(main())
