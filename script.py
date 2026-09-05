#!/usr/bin/env python3
import os
import sys
import re
import json
import requests
import time
from urllib.parse import urljoin, urlparse

# ---------- 配置 ----------
API_TOKEN = os.getenv('PIDGINHOST_API_TOKEN')
PANEL_BASE = 'https://www.pidginhost.com/'
PROXY = os.getenv('PROXY_SERVER')
TG_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID')
PANEL_COOKIE_RAW = os.getenv('PANEL_COOKIE')

if not API_TOKEN:
    print('❌ 缺少 PIDGINHOST_API_TOKEN')
    sys.exit(1)

if not PANEL_COOKIE_RAW:
    print('❌ 缺少 PANEL_COOKIE')
    sys.exit(1)

proxies = {'http': PROXY, 'https': PROXY} if PROXY else None

api_session = requests.Session()
api_session.headers.update({'Authorization': f'Token {API_TOKEN}', 'Content-Type': 'application/json'})
if proxies:
    api_session.proxies.update(proxies)

panel_session = requests.Session()
if proxies:
    panel_session.proxies.update(proxies)

panel_session.cookies.clear()

# 解析 Cookie
cookie_dict = {}
raw = PANEL_COOKIE_RAW.strip()
if raw.startswith('[') or raw.startswith('{'):
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            for item in data:
                if 'name' in item and 'value' in item:
                    cookie_dict[item['name']] = item['value']
        elif isinstance(data, dict):
            cookie_dict = data
    except json.JSONDecodeError:
        pass

if not cookie_dict:
    for pair in raw.split(';'):
        pair = pair.strip()
        if '=' in pair:
            k, v = pair.split('=', 1)
            cookie_dict[k] = v

panel_session.cookies.update(cookie_dict)

# ---------- 工具函数 ----------
def send_tg(text):
    if TG_TOKEN and TG_CHAT:
        try:
            requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                          data={'chat_id': TG_CHAT, 'text': text[:4096]}, timeout=10)
        except Exception as e:
            print(f'⚠️ TG 通知失败: {e}')

def get_csrf_token_and_action(session, url):
    resp = session.get(url, timeout=30)
    if resp.status_code != 200:
        return None, None, resp

    csrf_cookie = None
    for c in session.cookies:
        if c.name == 'csrftoken':
            csrf_cookie = c.value
            break
    if not csrf_cookie:
        match = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', resp.text)
        csrf_cookie = match.group(1) if match else None

    # 提取 action 值
    action_value = None
    action_match = re.search(r'name="action"\s+value="([^"]+)"', resp.text)
    if action_match:
        action_value = action_match.group(1)
    else:
        if 'extend_renewal' in resp.text:
            action_value = 'extend_renewal'
        elif 'renew' in resp.text:
            renew_match = re.search(r'value="([^"]*renew[^"]*)"', resp.text, re.I)
            action_value = renew_match.group(1) if renew_match else 'extend_renewal'
        else:
            action_value = 'extend_renewal'

    return csrf_cookie, action_value, resp

def extract_expiry_days(html_text):
    """
    从 HTML 中提取 "expires in X days" 或类似表述。
    返回天数（int）或 None。
    """
    # 直接匹配原始 HTML（不清理）
    patterns = [
        r'This\s+free\s+server\s+expires\s+in\s+(\d+)\s+days?',
        r'expires\s+in\s+(\d+)\s+days?',
        r'remaining\s+(\d+)\s+days?',
        r'(\d+)\s+days?\s+remaining',
        r'剩余\s*(\d+)\s*天',
        r'(\d+)\s+days?\s+left',
    ]
    for pat in patterns:
        match = re.search(pat, html_text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    # 若失败，清理标签后再试
    clean = re.sub(r'<[^>]+>', ' ', html_text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    for pat in patterns:
        match = re.search(pat, clean, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None

def get_page(url, session, allow_redirects=True, cache_control=True):
    """
    获取页面，可设置缓存控制头。
    返回 (响应对象, 最终URL)
    """
    headers = {}
    if cache_control:
        headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp = session.get(url, headers=headers, allow_redirects=allow_redirects, timeout=30)
    return resp, resp.url if allow_redirects else url

def get_current_days_for_url(url, session, max_retries=3, delay=2):
    """
    根据给定的 URL 获取当前剩余天数，重试 max_retries 次。
    返回 (天数, 响应对象, 最终URL) 或 (None, None, None)
    """
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(delay)
        resp, final_url = get_page(url, session, allow_redirects=True)
        if resp.status_code != 200:
            print(f'  ⚠️ 获取页面失败，状态码 {resp.status_code} (尝试 {attempt+1}/{max_retries})')
            continue
        days = extract_expiry_days(resp.text)
        if days is not None:
            return days, resp, final_url
        # 调试：打印页面片段
        snippet = resp.text[:300].replace('\n', ' ')
        print(f'  ⚠️ 未解析到天数 (尝试 {attempt+1}/{max_retries})，页面开头片段：{snippet}')
    return None, None, None

def renew_server_via_panel(server_id):
    """
    续期服务器，并验证天数是否增加。
    返回 (success, message, new_days)
    """
    # 1. 获取续期前的详情页 URL（用于提取旧天数）
    detail_url = urljoin(PANEL_BASE, f'panel/cloud/servers/{server_id}/')
    print('  ⏳ 获取续期前剩余天数...')
    old_days, _, _ = get_current_days_for_url(detail_url, panel_session, max_retries=2, delay=1)
    if old_days is None:
        print('  ⚠️ 无法获取续期前天数，将视为 0')
        old_days = 0

    # 2. 获取 CSRF token 和 action
    csrf_token, action_value, resp = get_csrf_token_and_action(panel_session, detail_url)
    if not csrf_token:
        if resp.status_code == 302:
            return False, "Cookie 过期或无效", None
        return False, f"无法获取 CSRF token (状态码 {resp.status_code})", None

    # 3. 发送续期 POST
    print('  🔄 发送续期请求...')
    data = {
        'csrfmiddlewaretoken': csrf_token,
        'action': action_value if action_value else 'extend_renewal'
    }
    headers = {'Referer': detail_url, 'X-CSRFToken': csrf_token}
    # 不允许自动重定向，以便我们捕获 Location
    post_resp = panel_session.post(detail_url, data=data, headers=headers, allow_redirects=False, timeout=30)

    if post_resp.status_code == 302:
        location = post_resp.headers.get('Location', '')
        if '/accounts/login/' in location:
            return False, "重定向到登录页，Cookie 失效", None
        # 使用 Location 作为续期后的目标 URL
        # 注意：Location 可能是相对路径，需要拼接
        if not location.startswith('http'):
            location = urljoin(PANEL_BASE, location)
        final_url = location
        print(f'  ✅ 收到续期重定向，Location: {location}')
    else:
        return False, f"续期请求失败 (状态码 {post_resp.status_code})", None

    # 4. 等待并获取续期后的天数（使用 Location URL）
    print('  ⏳ 等待并获取续期后剩余天数...')
    new_days = None
    for attempt in range(6):  # 最多尝试6次
        if attempt > 0:
            time.sleep(2)
        days, resp, final_url = get_current_days_for_url(final_url, panel_session, max_retries=1, delay=0)
        if days is not None:
            new_days = days
            break
        print(f'  ⚠️ 未解析到天数，重试 {attempt+1}/6')

    if new_days is None:
        return False, "续期后未能获取剩余天数", None

    # 5. 判断续期是否成功：免费服务器续期后应变为 30 天
    # 如果旧天数为 0，新天数为 30 => 成功
    # 如果旧天数为 30，新天数为 30 => 可能重复续期，也视为成功（因为天数未减少）
    if new_days >= old_days and new_days > 0:
        return True, f"续期成功（剩余 {new_days} 天）", new_days
    else:
        return False, f"续期异常（旧：{old_days} 天，新：{new_days} 天）", new_days

def fetch_all_servers():
    url = urljoin('https://www.pidginhost.com/api/', 'cloud/servers/')
    items = []
    while url:
        resp = api_session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get('results', []))
        url = data.get('next')
    return items

# ---------- 主逻辑 ----------
def main():
    try:
        # 验证 Cookie
        test_url = urljoin(PANEL_BASE, 'panel/')
        test_resp = panel_session.get(test_url, timeout=30)
        if test_resp.status_code != 200:
            print('❌ Cookie 无效或已过期，请重新导出并更新 PANEL_COOKIE')
            send_tg('❌ PidginHost 续期失败：Cookie 无效或过期')
            sys.exit(1)
        print('✅ Panel Cookie 有效')

        # 获取服务器列表
        print('📄 获取所有云服务器...')
        servers = fetch_all_servers()
        print(f'📋 找到 {len(servers)} 台服务器')

        renewed = 0
        failed = 0
        details = []

        for server in servers:
            sid = server['id']
            name = server.get('name', '未命名')
            print(f'🔄 尝试续期服务器 {sid} ({name})')

            success, msg, new_days = renew_server_via_panel(sid)
            if success:
                print(f'✅ {msg}')
                renewed += 1
                details.append(f'✅ 服务器 {sid} 续期成功（剩余 {new_days} 天）')
            else:
                print(f'❌ {msg}')
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
