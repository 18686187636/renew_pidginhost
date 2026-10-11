# PidginHost 自动续期

通过 GitHub Actions 自动续期 PidginHost 免费云服务器，内置 sing-box 代理支持。

## 架构

- `renew.py`：定时运行，用 `PANEL_COOKIE` 登录面板续期。
- `refresh_cookie.py`：手动运行，启动 Chrome + noVNC，你通过浏览器远程完成 GitHub OAuth，
  脚本自动把新 Cookie 写回 GitHub Secret。
- 两个 workflow 都会先用 `NODE_LINK` 启动 sing-box，再让脚本走本地代理。

## 私密变量

| Secret 名 | 说明 | 必需 |
|-----------|------|------|
| `PIDGINHOST_API_TOKEN` | PidginHost API Token | ✅ |
| `PANEL_COOKIE` | 面板 Cookie（首次手动填，之后自动更新） | ✅ |
| `GH_PAT` | GitHub PAT，需 `repo` 权限 | ✅ |
| `NODE_LINK` | vless:// 节点链接，用于代理 | ❌ |
| `TG_BOT_TOKEN` | Telegram Bot Token | ❌ |
| `TG_CHAT_ID` | Telegram Chat ID | ❌ |

> `NODE_LINK` 留空时自动跳过代理，直接连接。

## 代理说明

workflow 会自动：
1. 下载 sing-box（多个 GitHub 加速镜像轮询）
2. 解析 `NODE_LINK` 生成 sing-box 配置
3. 启动本地 SOCKS5（1080）和 HTTP（1081）代理
4. 把 `PROXY_SERVER` 设为 `http://127.0.0.1:1081`

支持的链接类型：`vless://`，含 `security=reality`、`type=ws/grpc/tcp`、`flow=xtls-rprx-vision` 等。

## 首次配置

### 1. 创建 GH_PAT

打开 https://github.com/settings/tokens，生成 Classic token，勾选 `repo`。
复制 `ghp_xxx...`。

### 2. 添加 Secrets

在仓库 `Settings → Secrets and variables → Actions` 添加上述所有 Secrets。

`PANEL_COOKIE` 可先留空。

### 3. 首次获取 Cookie

1. `Actions` → `Refresh PidginHost Cookie (noVNC)` → `Run workflow`。
2. 等待日志出现 `noVNC 公网地址：https://xxx.trycloudflare.com`。
3. 浏览器打开该地址，点 `Connect`。
4. 在远程 Chrome 里点击 `Sign in with GitHub`，完成登录 + 2FA + OAuth。
5. 脚本自动写回 `PANEL_COOKIE`。

### 4. 验证续期

`Actions` → `PidginHost Renew` → `Run workflow`，看日志。

## 日常使用

- `renew.yml` 每 12 小时自动跑一次。
- Cookie 过期时收到 Telegram 提醒，手动触发 `refresh-cookie.yml` 刷新。

## 常见问题

### sing-box 启动失败

看日志 `Show sing-box log on failure` 输出。常见原因：
- `NODE_LINK` 格式不对（目前只支持 vless）
- 节点本身失效

### noVNC 打开黑屏

等 5-10 秒或刷新。cloudflared 启动稍慢。

### 不需要代理怎么办

把 `NODE_LINK` Secret 删掉或留空，workflow 会自动跳过。
