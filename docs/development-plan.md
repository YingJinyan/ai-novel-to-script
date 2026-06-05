# 开发与提交计划

本文用于约束开发过程，确保每个阶段均有可复现、可审查的 Pull Request 和 commit 记录。

## 分支与提交规则

- 主分支：`main`
- 功能分支命名：`feat/<功能名>`
- 修复分支命名：`fix/<问题名>`
- 文档分支命名：`docs/<文档名>`
- 每个分支只解决一个问题。
- 合并前必须记录测试方式和测试结果。
- 不修改 commit 时间戳，不在截止日期后补造提交。

## 推荐 PR 清单

| 序号 | 分支示例 | 单一交付目标 |
| --- | --- | --- |
| 1 | `docs/yaml-schema` | 定义剧本 YAML Schema、设计原因和有效示例 |
| 2 | `feat/backend-bootstrap` | 建立后端服务、健康检查和基础测试 |
| 3 | `feat/chapter-parser` | 实现多章节文本解析和不少于 3 章的输入校验 |
| 4 | `feat/story-analysis` | 实现人物、场景、情节和时间线分析 |
| 5 | `feat/script-generation` | 实现分阶段剧本生成流水线 |
| 6 | `feat/schema-validation` | 实现 YAML 输出解析和 Schema 校验 |
| 7 | `feat/frontend-bootstrap` | 建立前端页面与基础交互 |
| 8 | `feat/import-workflow` | 实现小说导入、预览和错误提示 |
| 9 | `feat/script-editor` | 实现剧本预览、编辑、校验和导出 |
| 10 | `test/end-to-end` | 增加三章以上示例和端到端测试 |
| 11 | `docs/demo-and-deployment` | 完成部署、演示脚本和 README |

## PR 描述模板

```markdown
## 功能描述
说明本 PR 完成的单一功能及使用方式。

## 实现思路
说明技术选型、核心逻辑和重要取舍。

## 测试方式
列出执行命令、操作步骤及测试结果。

## 变更截图
涉及界面时提供截图；不涉及界面时填写“不适用”。
```

## 每次合并前检查

- 代码可运行，`main` 分支不会被破坏。
- PR 标题和描述与实际修改一致。
- 测试通过，并在 PR 中写明验证方式。
- 新增第三方依赖已在 README 中说明。
- 没有提交密钥、`.env`、测试输出或无关文件。

