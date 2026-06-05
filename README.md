# AI 小说转剧本工具

面向小说作者的 AI 辅助剧本创作工具。用户提交不少于 3 个章节的小说文本后，系统分析人物、场景、情节和章节关系，并生成符合约定 YAML Schema 的结构化剧本初稿，方便继续编辑与打磨。

## 项目目标

- 支持导入 3 个章节以上的小说文本。
- 自动识别人物、场景、情节节点和对白。
- 将跨章节内容转换为结构化 YAML 剧本。
- 提供 YAML 校验、错误提示和可编辑预览。
- 保存转换记录，并支持导出剧本文件。
- 提供独立的 YAML Schema 设计文档和示例。

## 计划中的核心体验

1. 导入或粘贴小说章节，检查章节数量与文本质量。
2. AI 分析人物关系、世界观、时间线和关键冲突。
3. 用户确认或调整改编设置，例如剧本类型、目标时长和风格。
4. 分阶段生成场次，再合并为完整剧本。
5. 在界面中查看、编辑、校验并导出 YAML 剧本。

## 架构草案

```text
frontend/
  Web 交互、进度展示、剧本预览与编辑
backend/
  文本解析、AI 编排、Schema 校验、任务与文件接口
docs/
  YAML Schema、架构、演示与开发过程文档
examples/
  示例小说输入与剧本输出
```

为提高长文本转换的稳定性，计划采用“章节分析 -> 全局故事规划 -> 分场生成 -> 一致性检查 -> YAML 校验”的流水线，而不是一次性要求模型生成整部剧本。

## 交付路线

| 阶段 | 交付内容 |
| --- | --- |
| 第 1 阶段 | 项目规划、技术选型、YAML Schema 与示例 |
| 第 2 阶段 | 小说导入、章节解析与输入校验 |
| 第 3 阶段 | AI 分析与结构化剧本生成流水线 |
| 第 4 阶段 | 剧本编辑、Schema 校验与 YAML 导出 |
| 第 5 阶段 | 测试、部署、README 完善与 Demo 视频 |

## 开发与提交规范

- `main` 分支始终保持可运行。
- 每项功能从独立分支开发，并通过 Pull Request 合并。
- 每个 PR 只完成一项明确任务，描述功能、实现思路和测试方式。
- 提交信息使用清晰的类型前缀，例如 `feat:`、`fix:`、`docs:`、`test:`、`chore:`。
- 第三方依赖及原创功能会在 README 中持续补充说明。

## 当前状态

项目初始化阶段。已完成项目定位、架构草案、交付路线、[竞品调研](docs/competitive-research.md)和[剧本 YAML Schema 设计](docs/yaml-schema.md)。

验证示例剧本：

```powershell
py -3.10 -m pip install -r requirements-dev.txt
py -3.10 scripts/validate_example.py
py -3.10 -m pytest -q
```

启动后端 API：

```powershell
py -3.10 -m pip install -r requirements.txt
py -3.10 -m uvicorn backend.main:app --reload
```

启动后可访问 `http://127.0.0.1:8000/docs` 查看接口文档。

## 原创功能说明

本项目将自主实现小说章节解析、长文本改编工作流、剧本 YAML Schema、生成结果校验和编辑交互。后续引入的第三方库、框架与模型服务将在此处逐项列明用途和版本。

## 当前第三方依赖

| 依赖 | 用途 |
| --- | --- |
| `PyYAML` | 读取和生成 YAML |
| `jsonschema` | 根据可执行 JSON Schema 验证剧本结构 |
| `pytest` | 自动测试 Schema 和业务一致性规则 |
| `FastAPI`、`Uvicorn` | 提供本地 HTTP API 与交互式接口文档 |
| `Pydantic` | 定义和验证 API 请求响应模型 |
| `httpx` | 支持 FastAPI 接口测试，后续用于模型服务请求 |

## License

本项目用于七牛云实训营作品开发。未经作者许可，不得复制或用于其他参赛作品。
