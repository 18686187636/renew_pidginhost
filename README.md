# PidginHost 自动续期

通过 GitHub Actions 自动续期 PidginHost 免费云服务器。

## 架构

- `renew.py`：定时运行，用 `PANEL_COOKIE` 登录面板续期。
- `refresh_cookie.py`：手动运行，启动 Chrome + noVNC，你通过浏览器远程完成 GitHub OAuth，
  脚本自动把新 Cookie 写回 GitHub Secret。

## 首次配置

### 1. Fork / 创建仓库

把本项目所有文件推送到你的 GitHub 仓库。

### 2. 添加 Secrets

仓库 `Settings → Secrets and variables → Actions`，添加：

| Secret 名 | 说明 |
|-----------|------|
| `PIDGINHOST_API_TOKEN` | PidginHost API Token |
| `PANEL_COOKIE` | 初始 Cookie（见下方"首次获取"） |
| `GH_PAT` | GitHub PAT，需 `repo` 权限 |
| `PROXY_SERVER` | 可选，代理地址 |
| `TG_BOT_TOKEN` | 可选，Telegram Bot Token |
| `TG_CHAT_ID` | 可选，Telegram Chat ID |

### 3. 首次获取 PANEL_COOKIE

手动触发一次 `Refresh PidginHost Cookie (noVNC)` workflow：

1. 进入仓库 `Actions` 页，选择 `Refresh PidginHost Cookie (noVNC)`，点 `Run workflow`。
2. 等待日志出现 `noVNC 公网地址：https://xxx.trycloudflare.com`。
3. 在浏览器打开该地址，点 `Connect`。
4. 在远程 Chrome 里：
   - 点击 `Sign in with GitHub`
   - 完成 GitHub 登录 + 2FA
   - 完成 OAuth 授权
   - 等页面跳回 PidginHost 面板
5. 脚本会自动检测并写回 `PANEL_COOKIE` Secret。

> 如果 `GH_PAT` 没配好，脚本会在日志里打印 Cookie 字符串，你手动复制到 Secret 也行。

## 日常使用

- `renew.py` 每 12 小时自动跑一次。
- Cookie 过期时，`renew.py` 会发 Telegram 提醒你。
- 收到提醒后，手动触发 `Refresh PidginHost Cookie (noVNC)` 即可。

## Cookie 有效期

PidginHost 的 session 通常能维持数周，取决于服务器端配置。脚本无法延长，
但可以自动刷新。

## 常见问题

### noVNC 打开是黑屏

等 5-10 秒，或刷新页面。cloudflared 有时启动稍慢。

### 无法访问 cloudflared 地址

某些地区可能屏蔽 `trycloudflare.com`。可改用其他隧道，如 ngrok、serveo。

### GitHub OAuth 被风控

CI 的 IP 是数据中心 IP，GitHub 可能要求邮箱验证码或设备验证。
因为用的是真实浏览器 + noVNC，你可以手动完成这些验证。

### 想彻底不用 Cookie

联系 `support@pidginhost.com`，请求为 GitHub OAuth 账户设置独立密码。
