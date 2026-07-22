---
inclusion: always
---

# 工作偏好

## 沟通风格
- 用中文回复
- 简洁直接，少废话，不要客套（"完全正确"、"好主意"这种开场白都省略）
- 复杂任务可以分点列，简单问题就直接答
- 代码块用 markdown，正文用纯文本

## 工作模式
- 默认 Autopilot 风格：能直接做的事就直接做，不要每步都问
- 小改动（单文件修复、重命名、加注释）直接动手
- 多文件改动或不熟悉的代码区域，先快速读一下再动
- 写完代码后自己跑构建/测试验证，有错就修
- 安全相关、删除多文件、改生产配置、动认证逻辑这类不可逆操作仍然先确认

## 项目技术栈
- 主项目：Python（FastAPI 风格的分层架构：api / application / domain / core）
- 数据库：SQLite（`account_manager.db`）
- 子项目：`customer_portal_api/`（独立 FastAPI 服务）
- 容器化：Docker / docker-compose
- 包管理：pip + `.venv`

## 命令偏好（Windows / PowerShell）
- 实际 shell 是 PowerShell，不是 cmd
- 命令分隔用 `;`，不要用 `&`（PowerShell 里 `&` 是调用运算符，会报 `AmpersandNotAllowed`）
- 可以用 PowerShell 原生命令（`Get-ChildItem`、`Test-Path` 等）或者兼容别名（`dir`、`type`）
- 路径反斜杠或正斜杠都行
- 长跑进程（dev server、watcher）用 `control_pwsh_process` 后台进程工具，不要直接阻塞执行

## 代码风格
- 跟随项目现有风格和约定，不要随便引入新依赖或新的架构模式
- 写 Python 时遵循类型注解、明确异常处理、避免裸 except
- 不要主动加测试，除非我明确要求
- 不要过度防御性编程，不要在简单 bug 修复时顺手"清理"周围代码

## 验证习惯
- 改完代码用 `getDiagnostics` 检查
- Python 改动若有 pytest 就跑相关测试
- Docker / 子服务改动提醒我手动验证

## 测试纪律
- **不要全量回归**。全量跑一次 1 分钟以上，太费时间。
- 默认只跑直接相关的测试节点：用 `pytest path/to/test_file.py::test_name` 精确点名，多个节点空格分隔。
- 改了某个文件最多跑该文件对应的 test 文件（`pytest tests/test_xxx.py`）；不要顺手把同目录其它 test 文件也带上。
- 单测失败修完后只重跑失败的那一两个用例，不重跑整个文件。
- 只有以下情况才跑跨文件的测试：
  - 改了被多个模块依赖的核心 / 共享代码（明确说出依赖关系再跑）
  - 我明确说"全量回归"或"跑完整测试"
- 跑测试用 `-q` 减少输出，不要 `-v`，除非要看具体失败原因。

## 不需要做的事
- 不要主动创建 README、CHANGELOG、文档 md（除非我说要）
- 不要解释"我在做什么"超过一两句
- 不要问"要不要继续"，能继续就继续
