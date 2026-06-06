# 七牛 AI 接入与可信边界

## 当前实现

项目将七牛 AI 作为可选提供商，调用官方 OpenAI 兼容接口：

- 默认地址：`https://api.qnaigc.com/v1/chat/completions`
- 鉴权：`Authorization: Bearer <API Key>`
- 输出格式：`response_format: {"type": "json_object"}`
- 官方参考：
  - [AI 大模型推理 API](https://developer.qiniu.com/aitokenapi/12882/ai-inference-api)
  - [支持的模型列表](https://developer.qiniu.com/aitokenapi/12884/ai-model-list)

配置环境变量：

```powershell
$env:QINIU_AI_API_KEY="你的 API Key"
py -3.10 -m uvicorn backend.main:app --reload
```

密钥只由后端读取。系统通过官方 `/v1/models` 接口读取当前账号可用模型，前端只接收模型 ID 列表，并允许用户选择本次生成使用的模型。可选环境变量 `QINIU_AI_MODEL` 用于设置默认模型。状态与模型接口都不会返回密钥。

## 为什么采用“确定性骨架 + AI 受限润色”

模型不直接生成整份剧本 YAML。系统先用本地规则生成符合 Schema 的章节、事件、场次与证据链，再允许模型润色：

- 项目梗概；
- 剧本概要；
- 已知场次的用途与动作文本。

模型不能通过输出契约修改来源章节 ID、事件 ID、原文证据位置和章节哈希。润色结果仍须通过 Schema、证据和覆盖质量门禁。
每个 AI 动作文本还必须逐字保留对应事件的来源证据摘录，否则系统拒绝该结果。

这种设计不能自动证明 AI 文案绝无语义新增，因此每次 AI 润色都会附加 `ai_semantic_review_required` 警告，要求作者复核。

## 失败策略

- 未配置密钥或模型：返回 `503 qiniu_provider_not_configured`。
- 上游连接、超时或 HTTP 错误：返回结构化错误，不自动伪装成本地 AI 成功。
- 输出不是合法 JSON 或缺少场次：拒绝结果。
- 润色结果未通过质量门禁：返回完整质量报告，不向用户提供“通过”结果。
- 无密钥或断网演示：使用明确标注的“离线规则模式（不调用 AI）”。

## 验证状态

已完成模拟 HTTP 契约测试、异常响应测试、受限输出测试与质量门禁测试。

仓库不包含真实七牛密钥。配置自己的合法密钥后，在设置密钥的同一个 PowerShell 窗口中运行：

```powershell
.\scripts\verify-qiniu.ps1
```

验收脚本会从七牛 `/v1/models` 核对模型，自动选择当前可用的已配置或推荐文本模型，真实执行一次三章小说受限润色，并检查结果确实标记为七牛 AI、至少包含 3 个场次、通过质量门禁且保留作者复核警告。需要指定模型时可追加 `-Model 模型ID`。脚本只打印非敏感摘要，不打印密钥或生成正文。只有脚本显示 `PASSED` 后，才能声明已完成真实七牛线上调用。
