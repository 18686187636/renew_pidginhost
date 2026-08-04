#!/usr/bin/env python3
import os
import sys
import re
import requests
from datetime import datetime, timezone
from urllib.parse import urljoin

# ---------- 配置 ----------
API_TOKEN = os.getenv('PIDGINHOST_API_TOKEN')
BASE_URL = 'https://www.pidginhost.com/api/'
PANEL_BASE = 'https://www.pidginhost.com/'
PROXY = os.getenv('PROXY_SERVER')
TG_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID')
EMAIL = os.getenv('PIDGINHOST_EMAIL')
PASSWORD = os.getenv('PIDGINHOST_PASSWORD')

if not API_TOKEN:
    print('❌ 缺少 PIDGINHOST_API_TOKEN')
    sys.exit(1)

proxies = {'http': PROXY, 'https': PROXY} if PROXY else None

# API session
api_session = requests.Session()
api_session.headers.update({'Authorization': f'Token {API_TOKEN}', 'Content-Type': 'application/json'})
if proxies:
    api_session.proxies.update(proxies)

# Panel session
panel_session = requests.Session()
if proxies:
    panel_session.proxies.update(proxies)

# ---------- 工具函数 ----------
def days_until(date_str):
    if not date_str:
        return None
    if date_str.endswith('Z'):
        date_str = date_str[:-1] + '+00:00'
    dt = datetime.fromisoformat(date_str)
    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
    return (dt - now).days

def fetch_all_pages(url):
    items = []
    while url:
        resp = api_session.get(url)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get('results', []))
        url = data.get('next')
    return items

def send_tg(text):
    if TG_TOKEN and TG_CHAT:
        try:
            requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                          data={'chat_id': TG_CHAT, 'text': text[:4096]}, timeout=10)
        except Exception as e:
            print(f'⚠️ TG 通知失败: {e}')

def get_csrf_token(session, url):
    resp = session.get(url)
    if resp.status_code != 200:
        return None, resp
    csrf_cookie = session.cookies.get('csrftoken')
    match = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', resp.text)
    html_token = match.group(1) if match else None
    token = csrf_cookie or html_token
    return token, resp

def login_panel(session):
    """使用 EMAIL 和 PASSWORD 登录 Panel"""
    if not EMAIL or not PASSWORD:
        return False
    login_url = urljoin(PANEL_BASE, 'panel/login/')
    # 获取 CSRF token
    csrf_token, resp = get_csrf_token(session, login_url)
    if not csrf_token:
        print('⚠️ 无法获取登录 CSRF token')
        return False
    data = {
        'csrfmiddlewaretoken': csrf_token,
        'username': EMAIL,
        'password': PASSWORD,
        'next': '/panel/'
    }
    login_resp = session.post(login_url, data=data, headers={'Referer': login_url})
    # 登录成功通常重定向到 /panel/
    if login_resp.status_code == 302:
        print('✅ Panel 登录成功')
        return True
    else:
        print(f'❌ Panel 登录失败 (状态码 {login_resp.status_code})')
        return False

def renew_via_panel(server_id):
    url = urljoin(PANEL_BASE, f'panel/cloud/servers/{server_id}/')
    csrf_token, resp = get_csrf_token(panel_session, url)
    if not csrf_token:
        if resp.status_code == 302:
            return False, "Panel 需要登录"
        return False, f"无法获取 CSRF token (状态码 {resp.status_code})"
    data = {'csrfmiddlewaretoken': csrf_token, 'action': 'extend_renewal'}
    headers = {'Referer': url, 'X-CSRFToken': csrf_token}
    post_resp = panel_session.post(url, data=data, headers=headers, allow_redirects=False)
    if post_resp.status_code == 302:
        return True, "续期成功 (Panel POST)"
    else:
        return False, f"续期失败 (状态码 {post_resp.status_code})"

def renew_via_api(server_id):
    endpoints = [
        f'cloud/servers/{server_id}/renew/',
        f'cloud/servers/{server_id}/extend/',
    ]
    for endpoint in endpoints:
        url = urljoin(BASE_URL, endpoint)
        try:
            resp = api_session.post(url, json={})
            if resp.status_code in (200, 201, 204):
                return True, f"续期成功 (API: {endpoint})"
            elif resp.status_code == 404:
                continue
            else:
                return False, f"续期失败 ({resp.status_code}): {resp.text[:200]}"
        except Exception as e:
            return False, f"请求异常: {e}"
    return False, "所有 API 端点均不可用 (404)"

# ---------- 主逻辑 ----------
def main():
    try:
        print('📄 获取所有云服务器...')
        servers = fetch_all_pages(urljoin(BASE_URL, 'cloud/servers/'))
        print(f'📋 找到 {len(servers)} 台服务器')

        # 尝试登录 Panel（如果提供了凭据）
        panel_logged_in = False
        if EMAIL and PASSWORD:
            panel_logged_in = login_panel(panel_session)
        else:
            # 检查是否已经通过 cookie 认证
            test_resp = panel_session.get(urljoin(PANEL_BASE, 'panel/'))
            if test_resp.status_code == 200:
                panel_logged_in = True
            else:
                print('⚠️ Panel 未登录，未提供 EMAIL/PASSWORD，将仅尝试 API 续期')

        renewed = 0
        failed = 0
        details = []

        for server in servers:
            sid = server.get('id')
            name = server.get('name', '未命名')
            # 打印所有键以便调试
            print(f'🔍 服务器 {sid} 的键: {list(server.keys())}')
            
            # 尝试多个日期字段
            expiry = None
            for field in ['expiry_date', 'expires_at', 'expiration_date', 'end_date', 'next_due_date']:
                if server.get(field):
                    expiry = server[field]
                    break
            if not expiry:
                print(f'⚠️ 服务器 {sid} 无到期时间，跳过')
                continue

            days = days_until(expiry)
            if days is None:
                continue
            print(f'🕒 服务器 {sid} ({name}) 还有 {days} 天到期')

            if days > 7:
                print(f'⏳ 暂不处理')
                continue

            # 尝试续期
            success, msg = renew_via_api(sid)
            if success:
                print(f'✅ {msg}')
                renewed += 1
                details.append(f'✅ 服务器 {sid} 续期成功 (API)')
                continue

            # API 失败，尝试 Panel（如果已登录）
            if panel_logged_in:
                success, msg = renew_via_panel(sid)
                if success:
                    print(f'✅ {msg}')
                    renewed += 1
                    details.append(f'✅ 服务器 {sid} 续期成功 (Panel)')
                    continue
                else:
                    print(f'⚠️ Panel 续期失败: {msg}')
            else:
                print(f'⚠️ Panel 未登录，无法使用 Panel 续期')

            # 所有方式均失败
            print(f'❌ 服务器 {sid} 续期失败: {msg}')
            failed += 1
            details.append(f'❌ 服务器 {sid} 续期失败: {msg}')

        summary = f'续期完成：成功 {renewed} 台，失败 {failed} 台'
        print(f'🎉 {summary}')
        full_text = f"PidginHost 续期\n{summary}\n详情：\n" + '\n'.join(details[-5:])
        send_tg(('✅ ' if failed == 0 else '⚠️ ') + full_text)
        sys.exit(0 if failed == 0 else 1)

    except Exception as e:
        error_msg = f'❌ 脚本异常: {e}'
        print(error_msg)
        send_tg(f'❌ 续期脚本崩溃\n{error_msg}')
        sys.exit(1)

if __name__ == '__main__':
    main()
