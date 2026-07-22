---
inclusion: always
---

# Superpowers (按需召唤)

这是 obra/superpowers 工作流在 Kiro 里的移植。每个 skill 都是一份独立的 steering 文件，**默认不加载**，需要时用 `#文件名` 召唤完整内容。

## 触发原则

**默认行为：按 `preferences.md` 干活，不主动召唤任何 skill，也不主动建议召唤。**

只有用户用 `#文件名` 显式召唤，或者明确说"按 TDD 做 / 走 brainstorming / 拆 plan"这类指令时，才加载对应 skill。

skill 速查（仅供需要时参考，**不要主动建议**）：

| 场景 | 召唤 |
|---|---|
| 用户明确说"先想方案/先设计" | `#superpowers-brainstorming` |
| 用户明确说"拆任务/写 plan" | `#superpowers-writing-plans` |
| 用户明确说"按 plan.md 执行" | `#superpowers-executing-plans` 或 `#superpowers-subagent-driven-development` |
| 用户明确说"按 TDD 做 / 先写测试" | `#superpowers-test-driven-development` |
| 用户明确说"系统性 debug / 定位根因" | `#superpowers-systematic-debugging` |
| 用户明确说"上线前验证 / 完整自检" | `#superpowers-verification-before-completion` |
| 想了解整个 skill 体系怎么用 | `#superpowers-using-superpowers` |

例外：如果用户的请求里出现了上面右列的 `#文件名`，按召唤的 skill 走。

## 已存档的 plan / spec

- `docs/superpowers/plans/` — 实施计划（task checkbox 清单）
- `docs/superpowers/specs/` — 设计文档

## 工作流速记

```
想法 → brainstorming → spec → writing-plans → plan
plan → executing-plans (单线) 或 subagent-driven-development (多 subagent)
写代码全程 → test-driven-development
卡住 → systematic-debugging
报告完成前 → verification-before-completion
```

## 与本仓库 preferences.md 的优先级

`preferences.md` > superpowers skills > 默认行为。

**默认完全按 preferences 走，不主动加测试、不主动召唤 TDD。**只有用户当次明确说"按 TDD 做"或显式召唤了 `#superpowers-test-driven-development`，才进入 TDD 流程。其它 skill 同理。
