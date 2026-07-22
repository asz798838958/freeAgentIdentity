# 参与贡献

感谢你对 aBaiAutoplus 的关注！欢迎提交 Issue 和 Pull Request。

## 开发环境

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 运行测试

```bash
pytest
```

运行单个测试文件：

```bash
pytest tests/test_api_health.py -v
```

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

- `feat:` 新功能
- `fix:` 修复
- `docs:` 文档
- `refactor:` 重构
- `test:` 测试
- `chore:` 构建/工具

## 添加新平台

1. 在 `platforms/` 下新建目录
2. 实现 `plugin.py`（继承 `BasePlatform`，用 `@register` 装饰器注册）
3. 实现 `browser_register.py`（浏览器注册逻辑）
6. 添加对应的测试

## 代码风格

- Python 代码遵循 PEP 8
- 类型注解尽量完整
- 中文注释和日志
