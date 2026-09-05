#!/usr/bin/env python3
import os
import sys
import re
import json
import requests
import time
from urllib.parse import urljoin

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
    从原始 HTML 中提取到期剩余天数。
    优先匹配精确文本 "This free server expires in X days"，再尝试其他通用模式。
    返回 (days, matched_snippet) 或 (None, None)
    """
    # 优先：精确匹配（无需清理）
    exact_pattern = r'This\s+free\s+server\s+expires\s+in\s+(\d+)\s+days?'
    match = re.search(exact_pattern, html_text, re.IGNORECASE)
    if match:
        days = int(match.group(1))
        # 提取片段用于调试
        start = max(0, match.start() - 50)
        end = min(len(html_text), match.end() + 50)
        snippet = html_text[start:end].strip().replace('\n', ' ')
        return days, snippet

    # 备选：清理 HTML 后用通用模式
    clean = re.sub(r'<[^>]+>', ' ', html_text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    patterns = [
        r'expires\s+in\s+(\d+)\s+days?',
        r'remaining\s+(\d+)\s+days?',
        r'(\d+)\s+days?\s+remaining',
        r'valid\s+for\s+(\d+)\s+days?',
        r'(\d+)\s+days?\s+left',
        r'剩余\s*(\d+)\s*天',
        r'到期.*?(\d+)\s*天',
        r'(\d+)\s+days?',
    ]
    for pat in patterns:
        match = re.search(pat, clean, re.IGNORECASE)
        if match:
            days = int(match.group(1))
            start = max(0, match.start() - 50)
            end = min(len(clean), match.end() + 50)
            snippet = clean[start:end].strip()
            return days, snippet

    return None, None

def renew_server_via_panel(server_id):
    url = urljoin(PANEL_BASE, f'panel/cloud/servers/{server_id}/')
    csrf_token, action_value, resp = get_csrf_token_and_action(panel_session, url)
    if not csrf_token:
        if resp.status_code == 302:
            return False, "Cookie 过期或无效", None
        return False, f"无法获取 CSRF token (状态码 {resp.status_code})", None

    # 发送续期 POST
    data = {
        'csrfmiddlewaretoken': csrf_token,
        'action': action_value if action_value else 'extend_renewal'
    }
    headers = {'Referer': url, 'X-CSRFToken': csrf_token}
    post_resp = panel_session.post(url, data=data, headers=headers, allow_redirects=False, timeout=30)

    if post_resp.status_code == 302:
        location = post_resp.headers.get('Location', '')
        if '/accounts/login/' in location:
            return False, "重定向到登录页，Cookie 失效", None

    # 等待并重试获取详情页，最多 5 次，每次间隔 2 秒
    max_retries = 5
    delay = 2
    days = None
    snippet = None
    detail_resp = None
    for attempt in range(max_retries):
        time.sleep(delay)
        detail_resp = panel_session.get(url, timeout=30)
        if detail_resp.status_code != 200:
            continue
        days, snippet = extract_expiry_days(detail_resp.text)
        if days is not None and days > 0:
            break

    if days is not None and days > 0:
        return True, f"续期成功（到期剩余 {days} 天）", f"{days} days"
    else:
        # 解析失败，但 POST 成功（302），打印调试信息
        if post_resp.status_code == 302 and detail_resp:
            # 尝试在原始 HTML 中搜索 "expires" 或 "30"
            if 'expires' in detail_resp.text.lower() or '30' in detail_resp.text:
                # 提取包含 "expires" 的片段
                idx = detail_resp.text.lower().find('expires')
                if idx != -1:
                    snippet = detail_resp.text[max(0, idx-50):idx+150].strip().replace('\n', ' ')
                    print(f"⚠️ 找到疑似天数片段: {snippet}")
                else:
                    print("⚠️ 页面中存在 '30' 但未找到 'expires'，可能文本结构变化。")
            else:
                print("⚠️ 页面中未找到 'expires' 或 '30'，可能续期未生效或页面异常。")
            return True, "续期成功（未解析到天数，但重定向成功）", None
        else:
            return False, "续期失败（未检测到续期成功标志）", None

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

            success, msg, new_exp = renew_server_via_panel(sid)
            if success:
                print(f'✅ {msg}')
                renewed += 1
                details.append(f'✅ 服务器 {sid} 续期成功' + (f'（{new_exp}）' if new_exp else ''))
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
