#!/usr/bin/env python3
import os
import sys
import requests
from datetime import datetime, timezone
from urllib.parse import urljoin

API_TOKEN = os.getenv('PIDGINHOST_API_TOKEN')
BASE_URL = 'https://www.pidginhost.com/api'
PROXY = os.getenv('PROXY_SERVER')
TG_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID')

if not API_TOKEN:
    print('❌ 缺少 PIDGINHOST_API_TOKEN')
    sys.exit(1)

proxies = {'http': PROXY, 'https': PROXY} if PROXY else None
session = requests.Session()
session.headers.update({'Authorization': f'Token {API_TOKEN}', 'Content-Type': 'application/json'})
if proxies:
    session.proxies.update(proxies)

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
        resp = session.get(url)
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

def renew_server(server_id):
    """尝试多个可能的续期端点"""
    endpoints = [
        f'cloud/servers/{server_id}/renew/',
        f'cloud/servers/{server_id}/extend/',
        # 若以上均不生效，可尝试其他候选
    ]
    for endpoint in endpoints:
        url = urljoin(BASE_URL, endpoint)
        try:
            resp = session.post(url, json={})
            if resp.status_code in (200, 201, 204):
                return True, f"续期成功 (端点: {endpoint})"
            elif resp.status_code == 404:
                continue  # 端点不存在，尝试下一个
            else:
                return False, f"续期失败 ({resp.status_code}): {resp.text[:200]}"
        except Exception as e:
            return False, f"请求异常: {e}"
    return False, "所有续期端点均不可用 (404)"

def main():
    try:
        print('📄 获取所有云服务器...')
        servers = fetch_all_pages(urljoin(BASE_URL, 'cloud/servers/'))
        print(f'📋 找到 {len(servers)} 台服务器')

        renewed = 0
        failed = 0
        details = []

        for server in servers:
            sid = server['id']
            name = server.get('name', '未命名')
            expiry = server.get('expiry_date') or server.get('next_due_date')
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
            success, msg = renew_server(sid)
            if success:
                print(f'✅ {msg}')
                renewed += 1
                details.append(f'✅ 服务器 {sid} 续期成功')
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
