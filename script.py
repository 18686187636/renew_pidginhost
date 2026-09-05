#!/usr/bin/env python3
import os
import sys
import re
import json
import requests
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

def renew_server_via_panel(server_id):
    """
    续期单台服务器，通过解析详情页中的 "expires in X days" 确认续期成功
    """
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

    # 如果 POST 返回 302 且跳转到登录页，直接失败
    if post_resp.status_code == 302:
        location = post_resp.headers.get('Location', '')
        if '/accounts/login/' in location:
            return False, "重定向到登录页，Cookie 失效", None

    # 等待一下，让服务器更新状态
    import time
    time.sleep(2)

    # 再次 GET 服务器详情页，解析到期信息
    detail_resp = panel_session.get(url, timeout=30)
    if detail_resp.status_code != 200:
        # 降级：如果 POST 是 302 且未跳转登录，就算成功（但记录警告）
        if post_resp.status_code == 302:
            return True, "续期成功（无法验证详情页，仅根据重定向判断）", None
        else:
            return False, f"续期失败，且无法获取详情页 (状态码 {detail_resp.status_code})", None

    # 去除 HTML 标签，获取纯净文本
    clean_text = re.sub(r'<[^>]+>', ' ', detail_resp.text)  # 用空格替换标签
    # 压缩多余空白
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    # 在纯净文本中查找 "expires in X days"
    match = re.search(r'expires\s+in\s+(\d+)\s+days?', clean_text, re.IGNORECASE)
    if match:
        days = int(match.group(1))
        if days > 0:
            return True, f"续期成功（到期剩余 {days} 天）", f"{days} days"
        else:
            return False, f"续期失败（到期剩余 {days} 天，未延长）", None
    else:
        # 未找到天数，可能页面结构变化，降级判断
        if post_resp.status_code == 302:
            # 尝试打印部分文本以便调试（非必需，可注释掉）
            # print(f"DEBUG: 页面前200字符: {clean_text[:200]}")
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
