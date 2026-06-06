# 作品提交清单

截止时间：**2026 年 6 月 7 日 23:59（北京时间）**。

## 已由仓库完成

- [x] 公开 GitHub 仓库：<https://github.com/YingJinyan/ai-novel-to-script>
- [x] 3 章以上小说解析和结构化 YAML 剧本生成。
- [x] YAML Schema 与设计原因文档。
- [x] 前后端可运行项目、测试和 README。
- [x] 持续 commit 与单功能 PR 记录。
- [x] PR 描述包含功能、实现思路和测试方式。
- [x] `.env` 已忽略，仓库只保存空白 `.env.example`。

## 提交前自动检查

在仓库根目录运行：

```powershell
.\scripts\check.ps1
git status
git log --oneline --all
```

确认：

- 所有检查通过。
- `git status` 没有未提交的正式修改。
- GitHub `main` 与本机一致。
- 仓库在无登录浏览器中可以访问。

## 需要项目所有者完成

### 1. 七牛线上验证

部署或录制七牛 AI 功能前申请合法 API Key 和可用模型，只在本机环境变量中设置。不要把 Key 发到聊天、视频、README、Issue、PR 或 Git。

在设置新密钥的同一个 PowerShell 窗口运行：

```powershell
.\scripts\verify-qiniu.ps1
```

只有输出 `PASSED: real Qiniu AI generation completed.` 后，才在 Demo 中声明真实线上调用已经验证。失败时保留错误信息并更换可用文本模型重试，不要用离线结果冒充 AI 成功。

验收通过后，继续在同一个 PowerShell 窗口运行：

```powershell
.\scripts\start-demo.ps1
```

这样演示后端才能继承新密钥。录制结束后运行 `.\scripts\stop-demo.ps1`。

如果未完成真实线上验证，Demo 只展示可靠兜底模式，并诚实说明七牛接口已实现但待密钥验证。

### 2. 录制 Demo 视频

按 [Demo 视频脚本](demo-script.md) 录制，建议 4–6 分钟。录制完成后上传到活动允许的平台，并确保评委无需申请权限即可观看。

### 3. 在活动页面提交

填写：

- GitHub 仓库地址：`https://github.com/YingJinyan/ai-novel-to-script`
- Demo 视频公开地址
- 项目简介：`可信、可控、可追溯的 AI 小说转剧本工作台`

提交后重新打开活动页面，确认链接和视频可访问。

## 密钥泄露应急

如果真实密钥曾进入 commit、PR、Issue、视频或聊天：

1. 立即在服务商后台禁用并重置该密钥。
2. 不要只删除当前文件，因为 Git 历史仍可能保存旧值。
3. 检查账单和调用记录。
4. 生成新密钥后只通过本机环境变量使用。
