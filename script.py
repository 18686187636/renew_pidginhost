#!/usr/bin/env python3
"""
PidginHost 自动续期脚本
- 通过 API 获取未支付发票
- 检查关联服务的到期时间，若 ≤7 天则使用余额支付
- 支持 SOCKS5 代理（通过环境变量 PROXY_SERVER）
- 发送 Telegram 通知
"""

import os
import sys
import requests
from datetime import datetime, timezone
from urllib.parse import urljoin
import time

# ---------- 配置 ----------
API_TOKEN = os.getenv('PIDGINHOST_API_TOKEN')
BASE_URL = 'https://www.pidginhost.com/api'
PROXY = os.getenv('PROXY_SERVER')          # 例如 socks5://127.0.0.1:1080
TG_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID')

if not API_TOKEN:
    print('❌ 环境变量 PIDGINHOST_API_TOKEN 未设置')
    sys.exit(1)

# 代理设置
proxies = {'http': PROXY, 'https': PROXY} if PROXY else None

session = requests.Session()
session.headers.update({
    'Authorization': f'Token {API_TOKEN}',
    'Content-Type': 'application/json'
})
if proxies:
    session.proxies.update(proxies)

# ---------- 工具函数 ----------
def days_until(date_str):
    """计算距离今天的天数（日期字符串为 ISO 格式）"""
    if not date_str:
        return None
    # 处理带时区的格式
    if date_str.endswith('Z'):
        date_str = date_str[:-1] + '+00:00'
    dt = datetime.fromisoformat(date_str)
    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
    return (dt - now).days

def fetch_all_pages(url):
    """处理 API 分页，返回所有结果列表"""
    items = []
    while url:
        resp = session.get(url)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get('results', []))
        url = data.get('next')
    return items

def send_tg_message(text):
    """发送 Telegram 消息"""
    if TG_TOKEN and TG_CHAT:
        try:
            requests.post(
                f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                data={'chat_id': TG_CHAT, 'text': text[:4096]},  # TG 限制
                timeout=10
            )
        except Exception as e:
            print(f'⚠️ TG 通知发送失败: {e}')

# ---------- 主逻辑 ----------
def main():
    try:
        print('💰 查询账户余额...')
        funds_resp = session.get(urljoin(BASE_URL, '/billing/funds/'))
        funds_resp.raise_for_status()
        balance = funds_resp.json().get('balance', 0)
        print(f'💰 当前余额: {balance}')

        print('📄 获取所有未支付发票...')
        all_invoices = fetch_all_pages(urljoin(BASE_URL, '/billing/invoices/'))
        unpaid = [inv for inv in all_invoices if inv.get('status') == 'unpaid']
        print(f'📄 未支付发票: {len(unpaid)} 张')

        renewed = 0
        failed = 0
        details = []

        for inv in unpaid:
            inv_id = inv['id']
            service_id = inv.get('service')
            if not service_id:
                print(f'⚠️ 发票 #{inv_id} 无关联服务，跳过')
                continue

            # 获取服务详情
            try:
                svc_resp = session.get(urljoin(BASE_URL, f'/billing/services/{service_id}/'))
                svc_resp.raise_for_status()
                service = svc_resp.json()
            except Exception as e:
                msg = f'⚠️ 无法获取服务 {service_id} 信息: {e}'
                print(msg)
                failed += 1
                details.append(msg)
                continue

            expiry = service.get('expiry_date') or service.get('next_due_date')
            if not expiry:
                print(f'⚠️ 服务 {service_id} 无到期时间，跳过')
                continue

            days = days_until(expiry)
            if days is None:
                continue
            print(f'🕒 服务 {service_id} ({service.get("name", "未命名")}) 还有 {days} 天到期')

            if days > 7:
                print(f'⏳ 暂不处理')
                continue

            # 检查余额
            if balance < inv.get('amount', 0):
                msg = f'❌ 余额不足支付发票 #{inv_id} (需 {inv["amount"]})'
                print(msg)
                failed += 1
                details.append(msg)
                continue

            # 支付
            try:
                pay_resp = session.post(
                    urljoin(BASE_URL, f'/billing/invoices/{inv_id}/pay-with-funds/'),
                    json={}
                )
                pay_resp.raise_for_status()
                msg = f'✅ 发票 #{inv_id} 支付成功'
                print(msg)
                renewed += 1
                details.append(msg)
            except Exception as e:
                msg = f'❌ 支付发票 #{inv_id} 失败: {e}'
                print(msg)
                failed += 1
                details.append(msg)

        # 输出汇总
        summary = f'续期结果：成功 {renewed} 张，失败 {failed} 张'
        print(f'🎉 {summary}')
        details_text = '\n'.join(details[-5:])  # 只取最后5条避免过长
        full_text = f"PidginHost 自动续期\n{summary}\n详情：\n{details_text}"

        # 发送 TG 通知（如果失败数 > 0 则标注）
        if failed > 0:
            full_text = '⚠️ ' + full_text
        else:
            full_text = '✅ ' + full_text
        send_tg_message(full_text)

        # 退出码：有失败则返回 1，让 GitHub 感知
        sys.exit(0 if failed == 0 else 1)

    except Exception as e:
        error_msg = f'❌ 脚本执行异常: {e}'
        print(error_msg)
        send_tg_message(f'❌ PidginHost 续期脚本崩溃\n{error_msg}')
        sys.exit(1)

if __name__ == '__main__':
    main()
