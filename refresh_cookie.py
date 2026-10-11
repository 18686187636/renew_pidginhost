#!/usr/bin/env python3
"""在 GitHub Actions 里启动 Chrome，通过 noVNC 手动完成 GitHub OAuth 登录 PidginHost，
导出 pidginhost.com 的 session cookies 并写回 GitHub Secret PANEL_COOKIE。"""

from __future__ import annotations

import base64
import os
import sys
import time

import requests
from nacl import encoding, public

from DrissionPage import ChromiumOptions, ChromiumPage

LOGIN_URL = "https://www.pidginhost.com/"
PANEL_HOST = "www.pidginhost.com"
WAIT_TIMEOUT = 40 * 60


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


def _is_logged_in(page: ChromiumPage, url: str) -> bool:
    """判断是否已成功进入 PidginHost 面板（已登录状态）"""
    if not url:
        return False
    if PANEL_HOST not in url:
        return False
    if "github.com" in url:
        return False

    url_lower = url.lower()

    # 1) URL 黑名单
    blocked_paths = (
        "/login", "/signup", "/register", "/oauth",
        "/account/register", "/account/login",
    )
    for p in blocked_paths:
        if p in url_lower:
            return False

    # 2) 必须落在 /panel/ 下
    if "/panel/" not in url_lower:
        return False

    # 3) 页面内容检查
    try:
        html = page.html or ""
    except Exception:
        html = ""
    html_lower = html.lower()

    if "sign in with github" in html_lower:
        return False
    if "create an account" in html_lower:
        return False
    if "sign up" in html_lower and "sign in" in html_lower:
        return False

    if "logout" in html_lower or "sign out" in html_lower or "sign-out" in html_lower:
        return True

    # 4) 兜底：明确需要登录的路径
    if any(k in url_lower for k in (
        "/panel/cloud/servers",
        "/panel/dashboard",
        "/panel/account/profile",
    )):
        return True

    return False


def main() -> int:
    novnc_url = os.environ.get("NOVNC_URL", "").strip()
    print("=" * 70)
    if novnc_url:
        print(f"📺 noVNC 地址: {novnc_url}")
    else:
        print("📺 未获取到 NOVNC_URL，请查看 workflow 日志")
    print("=" * 70)

    co = ChromiumOptions()
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-infobars")
    co.set_argument("--lang=zh-CN,zh;q=0.9,en;q=0.8")
    co.set_argument("--window-size=1280,800")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--start-maximized")

    co.headless(False)

    proxy = os.environ.get("PROXY_SERVER", "").strip()
    if proxy:
        print(f"[setup] 使用代理: {proxy}")
        try:
            co.set_proxy(proxy)
        except Exception as exc:
            print(f"[setup] 设置代理失败: {exc}")

    for path in ("/usr/local/bin/chromium", "/usr/bin/chromium",
                 "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
        if os.path.exists(path):
            co.set_browser_path(path)
            print(f"[setup] 使用 Chrome: {path}")
            break

    co.auto_port()
    page = ChromiumPage(co)
    page.get(LOGIN_URL)

    print("=" * 70)
    print("✅ Chrome 已打开 PidginHost 首页")
    print("")
    print("请在 noVNC 里：")
    print("  1. 点击页面右上角的 'Sign in'（或 'Login' / 'Client Area'）")
    print("  2. 选择 'Sign in with GitHub'")
    print("  3. 完成 GitHub 登录 + 2FA + OAuth 授权")
    print("  4. 等待页面跳回 PidginHost 面板（不是注册页！）")
    print("")
    print(f"脚本会等待最多 {WAIT_TIMEOUT // 60} 分钟，真正进入面板后自动导出 Cookie")
    print("=" * 70)

    deadline = time.time() + WAIT_TIMEOUT
    last_url = ""
    last_print = 0

    while time.time() < deadline:
        now = time.time()
        try:
            url = page.url
        except Exception:
            url = ""

        if url and url != last_url:
            print(f"[setup] URL 变化: {url}")
            last_url = url

        if _is_logged_in(page, url):
            print("[setup] ✅ 检测到已登录，等待 5 秒让 session 稳定...")
            time.sleep(5)
            return _export_and_save(page)

        if now - last_print >= 30:
            remaining = int(deadline - now)
            print(f"[setup] ⏳ 仍在等待登录... 剩余 {remaining} 秒，当前 URL: {url or '(加载中)'}")
            last_print = now

        time.sleep(2)

    print("[setup] ❌ 超时未完成登录")
    return 1


def _export_and_save(page: ChromiumPage) -> int:
    # 保险：再确认一次 URL
    try:
        final_url = (page.url or "").lower()
    except Exception:
        final_url = ""
    for bad in ("/register", "/login", "/signup", "/oauth"):
        if bad in final_url:
            print(f"[setup] ❌ 当前仍在未登录页面（{final_url}），放弃导出")
            return 1

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
        print("[setup] ❌ 没有找到 sessionid，无法导出")
        return 1

    cookie_str = "; ".join(f"{k}={v}" for k, v in wanted.items())
    print(f"[setup] PANEL_COOKIE 长度: {len(cookie_str)}")

    _update_secret("PANEL_COOKIE", cookie_str)
    return 0


def _update_secret(name: str, value: str) -> None:
    token = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()

    if not token or not repo:
        print("=" * 70)
        print(f"[setup] ⚠️ 未配置 GH_PAT 或 GITHUB_REPOSITORY")
        print(f"[setup] 请手动复制下面这段到 Secret {name}")
        print("=" * 70)
        print(value)
        print("=" * 70)
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
