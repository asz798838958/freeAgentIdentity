# aBaiAutoplus

一个面向本地部署的账号注册、登录恢复、验活和资源池管理平台。项目提供 FastAPI 后端与 React 管理界面，把协议注册、浏览器注册、密码与 2FA、401 刷新、邮箱池和代理池串成一套可观察、可停止、可复用的任务流程。
- QQ 群：<https://qm.qq.com/q/JigtiO2Hyc>
- 群二维码：[assets/screenshots/QQ群交流.jpg](assets/screenshots/QQ群交流.jpg)
## 核心功能

### 注册方式

- **协议注册**：通过 HTTP 协议流程完成注册、邮箱验证码处理、密码设置和账号凭据保存。
- **有头浏览器注册**：使用 Camoufox 浏览器执行注册流程，可在需要时通过 VNC 观察页面操作。
- **无头浏览器注册**：使用 Camoufox headless 模式运行批量注册任务，支持并发、代理池和任务日志。
- **密码 + 2FA**：自动注册固定设置远端密码；注册成功后绑定并激活 TOTP 2FA，密码、TOTP 密钥和账号凭据一并保存。注册或绑定失败的账号不会写入成功结果。
- **验证码处理**：按已启用的 provider 选择远程验证码服务、本地 solver 或人工处理，并从邮箱池读取邮箱验证码。

### 401 验活与登录恢复

- 账号列表显示 access token / refresh token 状态和 401 状态。
- 一键创建 **401 验活任务**，先用 Camoufox 并行检查账号；失活账号再进入协议登录流程获取新的 access token。
- 协议恢复登录使用账号已保存的邮箱、密码和 TOTP 2FA；必要时读取新的邮箱验证码。
- 刷新成功后更新 access token、refresh token 和账号状态，失败原因写入任务日志，方便继续处理。

### 邮箱池管理

支持在设置页维护多种邮箱来源，并在注册任务中选择本次使用的邮箱服务：

- **本地微软邮箱池**：导入 Outlook / Hotmail 邮箱凭据，支持 Microsoft Graph 读取验证码；默认按邮箱使用次数原子分配。
- **API 邮箱池**：每行配置一个邮箱和对应的验证码 API，支持轮询间隔、请求超时、占用状态和是否允许复用。
- **自有域名 IMAP 全收**：为每次注册生成独立地址，从 catch-all IMAP 收件箱读取验证码。
- **自有域名 Inbucket**：通过 Inbucket SMTP/API 生成地址并读取验证码，适合本地开发和测试。
- 邮箱池页面提供总量、已使用、已耗尽、预留和收件箱查询等统计；注册失败会释放邮箱租约，成功才提交使用记录。

### 代理池管理

- 管理 Mihomo 代理订阅来源，并同步全部代理节点。
- 查看节点延迟、存活状态、当前选中节点和 UDP 状态。
- 支持启用/停用节点、切换当前节点、刷新订阅和测速。
- 注册任务可选择 Mihomo 代理池、动态 IP 提取 API 或本机直连。
- 代理池注册支持脉冲调度：按健康节点分波并发，节点异常或 IP 被封时暂停分配并定时探测恢复。

### 任务与账号管理

- 注册、401 验活、协议恢复等任务统一进入任务中心。
- 支持设置注册数量、并发数、邮箱 provider、代理模式和脉冲探测参数。
- 任务日志实时展示，页面刷新后可恢复任务状态；任务可以从界面停止。
- 账号列表支持搜索、分页、只看有 refresh token、查看 401 状态和存活率。
- 一键复制账号、密码、TOTP 信息和 2FA 查看链接，便于后续登录或导出。
- 启动后会显示 QQ 群二维码弹窗，可从弹窗加入交流群获取教程和更新信息。

## 运行环境

- Python 3.11+
- Node.js 18+
- npm
- Chromium/Camoufox 运行依赖（浏览器注册或验活时需要）
- Mihomo（使用代理池时需要）

## 本地运行

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..

python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

浏览器访问 <http://127.0.0.1:8000>。前端开发模式：

```bash
cd frontend
npm run dev
```

## Docker

```bash
docker compose up --build
```

Docker Compose 会启动 API、前端静态资源和项目配置的可选依赖。浏览器、Mihomo 和邮箱服务是否启用，取决于本地配置和部署环境。

## 基本配置

```bash
cp .env.example .env
```

至少设置一个随机的 `APP_PASSWORD`，再在管理界面配置：

1. 注册邮箱 provider 和邮箱池凭据；
2. 验证码 provider；
3. Mihomo 订阅或动态代理 API；
4. 默认注册方式和执行方式；
5. 数据库、加密密钥和任务并发参数。

示例：

```env
APP_PASSWORD=<请使用密码管理器生成的随机值>
ACCOUNT_MANAGER_DATABASE_URL=sqlite:///./data/account_manager.db
BACKGROUND_JOBS_ENABLED=0
APP_RUNTIME_MODE=desktop
```

更多字段和 provider 配置见 [docs/configuration.md](docs/configuration.md)。

## 目录结构

```text
api/                    FastAPI 路由：账号、任务、配置、邮箱、代理
application/            任务编排和应用服务
core/                   数据库、配置、凭据加密、邮箱抽象和通用逻辑
infrastructure/         repository、provider 定义和持久化实现
platforms/chatgpt/      协议注册、浏览器注册、验活、登录恢复和 2FA
frontend/               React + Vite 管理界面
tests/                  单元测试和集成测试
docs/                   配置、发布和贡献说明
```

## 测试与构建

```bash
# 后端测试
pytest -q

# 前端构建
cd frontend
npm run build
cd ..

# 检查补丁格式
git diff --check
```

## 数据与凭据

邮箱密码、refresh token、Cookie、TOTP 密钥、代理凭据和第三方 API key 请只放在本地 `.env`、数据库或 Secret 管理中，不要提交到 Git。生产环境请使用自己控制的邮箱、代理和服务配置，并定期备份数据库和加密密钥。

## 许可证

本项目使用 [AGPL-3.0](LICENSE)。第三方依赖仍分别受其各自许可证约束。
