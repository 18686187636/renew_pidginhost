# PidginHost 免费服务器自动续期

[![PidginHost Auto Renew](https://github.com/your-username/renew_pidginhost/actions/workflows/renew.yml/badge.svg)](https://github.com/your-username/renew_pidginhost/actions/workflows/renew.yml)

通过 GitHub Actions 自动续期 PidginHost 免费服务器（每 30 天约 3 次），并发送 Telegram 通知。支持通过代理访问（Sing‑box），适用于网络受限环境。

---

## 📌 功能特性

- 🔄 **自动续期**：每 10 天运行一次（即每 30 天约 3 次），确保服务器不会过期。
- 🍪 **Cookie 认证**：使用浏览器导出的 `sessionid` 和 `csrftoken` 模拟登录 Panel，无需用户名/密码。
- 🔗 **代理支持**：通过 `NODE_LINK` 配置 Sing‑box 代理，适用于需要代理访问 PidginHost 的场景。
- 🤖 **Telegram 通知**：续期结果（成功/失败数量）实时推送到您的 Telegram。
- 🚀 **完全自动化**：部署后无需人工干预，由 GitHub Actions 定时触发。

---

## 🛠️ 准备工作

1. **GitHub 仓库**：Fork 或新建一个仓库用于存放工作流脚本。
2. **PidginHost 账号**：需已登录（支持 GitHub OAuth）。
3. **Telegram Bot**：用于接收通知（[BotFather](https://t.me/BotFather) 创建）。

---

## 🔐 环境变量（Secrets）

在仓库的 `Settings → Secrets and variables → Actions` 中添加以下 Secret：

| Secret 名称 | 说明 | 获取方式 |
|------------|------|----------|
| `PIDGINHOST_API_TOKEN` | PidginHost API Token | 控制台 → Account → API Tokens → 创建 |
| `PANEL_COOKIE` | 浏览器 Cookie（`sessionid` + `csrftoken`） | 见下文“获取 Cookie” |
| `TG_BOT_TOKEN` | Telegram Bot Token | BotFather 创建后获得 |
| `TG_CHAT_ID` | Telegram 聊天 ID（用户或群组） | 向 Bot 发送消息后，通过 `getUpdates` 获取 |
| `NODE_LINK` | （可选）Sing‑box 订阅链接（vless:// 格式） | 代理服务商提供 |

---

## 🍪 获取 `PANEL_COOKIE`

1. 在浏览器中登录 PidginHost（保持登录状态）。
2. 按 `F12` → **Application**（或“存储”）→ **Cookies** → 选择 `https://www.pidginhost.com`。
3. 复制 `sessionid` 和 `csrftoken` 的值，组合成以下格式：
   ```
   sessionid=你的sessionid; csrftoken=你的csrftoken
   ```
4. 将整个字符串作为 `PANEL_COOKIE` 的值添加到 Secrets。

> **注意**：`sessionid` 通常有效期较长（约 1 年），但若过期，请重新导出并更新 Secret。

---

## 📁 部署步骤

1. **将以下文件放入仓库根目录**：
   - `.github/workflows/renew.yml`（工作流定义）
   - `script.py`（续期核心脚本）

2. **添加所有 Secrets**（参考上面的表格）。

3. **推送代码**到默认分支（如 `main`）。

4. **手动触发测试**：
   - 进入仓库的 **Actions** 页面 → 选择 `PidginHost Auto Renew` → 点击 **Run workflow** → 观察日志。

---

## ⚙️ 工作流说明

- **触发时机**：
  - 定时：`cron: '0 0 */10 * *'`（每 10 天 UTC 00:00 运行）。
  - 手动：支持 `workflow_dispatch`。
- **步骤概览**：
  1. 检出代码，安装 Python 及依赖（`requests[socks]`）。
  2. （可选）下载并启动 Sing‑box 代理（若 `NODE_LINK` 存在）。
  3. 执行 `script.py`，使用 API Token 获取服务器列表，并通过 Cookie 认证 Panel 执行续期。
  4. 脚本内部发送 Telegram 通知（仅一条，包含详细结果）。

---

## 📜 脚本逻辑（`script.py`）

1. **解析 Cookie**：从 `PANEL_COOKIE` 中提取 `sessionid` 和 `csrftoken`，注入到 `requests.Session`。
2. **验证 Cookie**：访问 Panel 首页（`/panel/`），若返回 200 则有效。
3. **获取服务器列表**：调用 `/api/cloud/servers/` 获得所有服务器 ID。
4. **逐个续期**：
   - 对于每台服务器，访问 `/panel/cloud/servers/{id}/`，提取 CSRF token。
   - 发送 POST 请求，携带 `action=extend_renewal`。
   - 若返回 302（重定向）则认为续期成功。
5. **发送通知**：汇总成功/失败数量，通过 Telegram Bot 发送消息。

---

## 📊 通知示例

```
✅ PidginHost 续期
续期完成：成功 1 台，失败 0 台
详情：
✅ 服务器 4386 续期成功
```

---

## ❓ 常见问题

### 1. 提示“缺少 PANEL_COOKIE”或“Cookie 无效”
- 检查 Secret 名称是否准确（`PANEL_COOKIE` 全大写）。
- 重新导出最新 Cookie，并确保格式正确。
- 在 Actions 日志中查看 `✅ Panel Cookie 有效` 确认。

### 2. 续期失败，状态码非 302
- 可能 Cookie 已过期，重新导出更新。
- 检查网络环境，若需要代理，确保 `NODE_LINK` 有效且代理启动成功。

### 3. 如何修改续期频率？
- 编辑 `.github/workflows/renew.yml` 中 `cron` 表达式（如改为 `'0 0 1,15 * *'` 每月 1 号和 15 号）。

### 4. API Token 有什么用？没有会怎样？
- API Token 用于获取服务器列表。若没有，您需要手动在脚本中硬编码服务器 ID（不推荐）。建议保留。

### 5. 能否仅使用邮箱/密码登录？
- 若您使用邮箱注册而非 GitHub OAuth，可在脚本中启用用户名/密码登录（需修改代码），但本方案推荐使用 Cookie，更安全且无需额外依赖。

---

## 🤝 贡献

欢迎提交 Issue 或 PR 以改进脚本。如有任何问题，请附上 Actions 日志以便排查。

---

## 📄 许可证

MIT License

---

**Happy automating!** 🚀
