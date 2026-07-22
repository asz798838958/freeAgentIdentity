# aBaiAutoplus

aBaiAutoplus 是一个以 ChatGPT free 账号注册、管理和本地配置为主的 Web 面板。当前公开前端侧栏只暴露三个顶层入口：`总览`、`chatgpt free`、`设置`。

本 README 仅按当前前端可见菜单描述项目能力。代码中可能仍存在历史页面、内部路由或实验组件，但它们不属于当前公开入口。

## 当前可见菜单

### 总览

用于查看系统和账号整体状态：

- 账号总数、试用、订阅、异常等统计卡片
- 平台账号分布和状态分布
- Cursor、Kiro、ChatGPT 等桌面环境状态
- 手动刷新当前统计数据


### chatgpt free

用于管理 ChatGPT free 账号：

- 查看 ChatGPT 账号列表、状态、邮箱和账号详情
- 自动注册账号，支持配置注册数量、并发、注册身份和执行方式
- 批量选择、导出和复制账号信息
- 注册完成后可按页面配置处理工作区加入和本地结果导出
- 查看任务日志和账号动作执行结果

### 设置

设置页的子菜单当前全部保留：

| 子菜单     | 用途                                         |
| ---------- | -------------------------------------------- |
| 通用       | 主题、语言、默认注册策略、浏览器复用配置     |
| 注册策略   | 默认注册身份、执行方式、OAuth 相关默认值     |
| 邮箱服务   | 邮箱 provider 的新增、启用、默认项和参数配置 |
| 验证服务   | 验证码 provider 和求解策略配置               |
| 接码服务   | 接码 provider 的新增、启用、默认项和参数配置 |
| 代理资源   | 静态代理、动态代理和代理资源管理             |
| ChatGPT    | ChatGPT 平台相关配置                         |
| BitBrowser | BitBrowser Profile 池管理                    |
| 高级       | 高级配置和平台能力覆盖                       |
| 关于       | 当前版本、更新检查、项目链接和许可信息       |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- npm

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd frontend
npm install
npm run build
cd ..

python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

启动后访问 `http://localhost:8000`。

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
npm run build
cd ..

python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 前端开发模式

```bash
cd frontend
npm install
npm run dev
```

前端开发服务默认运行在 `http://localhost:5173`，后端仍需单独启动。

### Docker

```bash
docker compose up -d --build
```

默认 Web UI 端口为 `8000`。如果部署到公网，请务必设置访问密码。

## 配置说明

常用配置优先在 `设置` 页面完成；也可以按需复制 `.env.example` 为 `.env`，通过环境变量覆盖后端默认值。

公网或多人环境建议至少配置：

```env
APP_PASSWORD=change-me
ACCOUNT_MANAGER_DATABASE_URL=sqlite:///./data/account_manager.db
```

本地浏览器自动化相关能力需要安装浏览器运行时：

```bash
python -m playwright install chromium
```

## 项目结构

```text
.
├── main.py                 # FastAPI 入口
├── application/            # 任务、接口和应用层逻辑
├── core/                   # 核心模型、配置和通用能力
├── frontend/               # React + Vite 前端
├── platforms/chatgpt/      # ChatGPT 平台适配
├── tests/                  # 自动化测试
├── docker-compose.yml      # Docker 启动配置
└── requirements.txt        # Python 依赖
```

## 常用验证

```bash
pytest

cd frontend
npm run build
```

针对侧栏菜单的测试位于 `tests/test_frontend_sidebar_nav.py`。

## 安全说明

不要把以下内容提交到公开仓库：

- 真实账号、邮箱、手机号、密码、Cookie、Token、Session
- 第三方服务 API key、代理账号、浏览器配置和本地 profile 数据
- 本地数据库、导出文件、任务日志、短信或一次性验证码记录
- 浏览器抓包、页面快照、调试转储和任何包含私人信息的测试材料

如果敏感内容已经进入 Git 历史，仅删除文件不够，需要按 GitHub 官方文档重写仓库历史并强制推送；同时应立即轮换已经暴露的密钥、账号和凭据。

## 免责声明

本项目仅供学习、研究和自用自动化管理场景参考。使用者需要自行确认行为符合目标平台服务条款、当地法律法规和第三方服务规则。因使用本项目产生的后果由使用者自行承担。

## 许可

本项目使用 AGPL-3.0 许可证。项目基于 `lxf746/any-auto-register` 的插件化注册框架二次开发，感谢原作者的开源工作。
