#!/usr/bin/env python3
import os
import sys
import re
import json
import requests
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta

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

# API session
api_session = requests.Session()
api_session.headers.update({'Authorization': f'Token {API_TOKEN}', 'Content-Type': 'application/json'})
if proxies:
    api_session.proxies.update(proxies)

# Panel session
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
    """
    获取 CSRF token 和续期 action 参数（从 HTML 中动态提取）
    """
    resp = session.get(url)
    if resp.status_code != 200:
        return None, None, resp

    # 从 cookie 中获取 csrftoken
    csrf_cookie = None
    for c in session.cookies:
        if c.name == 'csrftoken':
            csrf_cookie = c.value
            break
    if not csrf_cookie:
        match = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', resp.text)
        csrf_cookie = match.group(1) if match else None

    # 从 HTML 中提取 action 值（续期操作名）
    action_value = None
    # 通常续期按钮是一个表单，包含 input name="action" value="extend_renewal"
    # 也可能在其他地方，我们尽量匹配
    # 先尝试找 input 标签
    action_match = re.search(r'name="action"\s+value="([^"]+)"', resp.text)
    if action_match:
        action_value = action_match.group(1)
    else:
        # 可能是一个按钮或表单 action 参数，我们尝试查找带有 "extend" 或 "renew" 的 value
        # 如果没找到，默认使用 'extend_renewal'（保守）
        if 'extend_renewal' in resp.text:
            action_value = 'extend_renewal'
        elif 'renew' in resp.text:
            # 尝试提取第一个包含 renew 的 value
            renew_match = re.search(r'value="([^"]*renew[^"]*)"', resp.text, re.I)
            if renew_match:
                action_value = renew_match.group(1)
            else:
                action_value = 'extend_renewal'  # 默认
        else:
            action_value = 'extend_renewal'  # 默认

    return csrf_cookie, action_value, resp

def get_server_expiration(server_id):
    """
    通过 API 获取指定服务器的到期时间（字符串），若不存在则返回 None
    """
    url = urljoin('https://www.pidginhost.com/api/', f'cloud/servers/{server_id}/')
    try:
        resp = api_session.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            # 尝试多种可能的字段名
            for key in ['expiration_date', 'expire_date', 'expires_at', 'expiry']:
                if key in data:
                    return data[key]
    except Exception as e:
        print(f'⚠️ 获取服务器 {server_id} 到期时间失败: {e}')
    return None

def renew_server_via_panel(server_id):
    """
    续期单台服务器，并验证是否真正成功
    返回 (success, message, new_expiration)
    """
    url = urljoin(PANEL_BASE, f'panel/cloud/servers/{server_id}/')
    csrf_token, action_value, resp = get_csrf_token_and_action(panel_session, url)
    if not csrf_token:
        if resp.status_code == 302:
            return False, "Cookie 过期或无效", None
        return False, f"无法获取 CSRF token (状态码 {resp.status_code})", None

    # 记录续期前的到期时间（如果有）
    old_exp = get_server_expiration(server_id)

    # 发送续期 POST 请求
    data = {
        'csrfmiddlewaretoken': csrf_token,
        'action': action_value if action_value else 'extend_renewal'
    }
    headers = {'Referer': url, 'X-CSRFToken': csrf_token}
    post_resp = panel_session.post(url, data=data, headers=headers, allow_redirects=False, timeout=30)

    # 判断是否成功：状态码 302 且重定向到服务器详情页
    if post_resp.status_code == 302:
        location = post_resp.headers.get('Location', '')
        # 检查 Location 是否指向详情页（而不是登录页或其它）
        if '/panel/cloud/servers/' in location:
            # 进一步验证：获取新的到期时间，对比是否变化
            new_exp = get_server_expiration(server_id)
            if old_exp is not None and new_exp is not None:
                # 尝试解析日期比较（简化：只要字符串不同就认为更新）
                if old_exp != new_exp:
                    return True, f"续期成功（到期时间更新为 {new_exp}）", new_exp
                else:
                    # 可能续期无效，但面板返回 302，这种情况罕见，但记录警告
                    return False, "续期操作返回 302，但到期时间未变化，可能续期失败", new_exp
            else:
                # 无法验证到期时间，仅凭重定向成功，保守认为成功（但提示无法验证）
                return True, "续期成功（无法验证到期时间，仅根据重定向判断）", None
        else:
            # 重定向到非详情页（如登录页）
            return False, f"重定向到非详情页: {location}", None
    else:
        # 非 302，直接失败
        return False, f"续期失败 (状态码 {post_resp.status_code})", None

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
                details.append(f'✅ 服务器 {sid} 续期成功')
                if new_exp:
                    details[-1] += f'（到期 {new_exp}）'
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
