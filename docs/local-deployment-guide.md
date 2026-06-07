# 本地部署与七牛 AI 配置教程

本教程面向第一次运行本项目的用户和评委。完成后，可在 Windows 电脑浏览器中打开溯源剧本工作台，并选择是否调用七牛 AI。

> 本地地址 `http://127.0.0.1:5173` 只能由当前电脑访问，不是公网网站。评委可以按照本教程在自己的电脑复现；远程观看作品请使用 Demo 视频。

## 1. 准备软件

需要安装：

- [Git](https://git-scm.com/download/win)
- [Python 3.10](https://www.python.org/downloads/release/python-31011/)
- [Node.js 22 LTS](https://nodejs.org/)

安装 Python 时勾选 **Add Python to PATH**。安装完成后打开新的 PowerShell，检查：

```powershell
git --version
py -3.10 --version
node --version
npm --version
```

四条命令均显示版本号后再继续。

## 2. 下载项目

在 PowerShell 中执行：

```powershell
cd D:\job
git clone https://github.com/YingJinyan/ai-novel-to-script.git
cd ai-novel-to-script
```

如果已经下载项目，只需进入现有目录：

```powershell
cd D:\job\ai_novel_to_script
```

## 3. 首次安装依赖

在项目根目录执行：

```powershell
py -3.10 -m pip install -r requirements-dev.txt
cd frontend
npm install
cd ..
```

这些命令只需在首次运行或依赖更新后执行。

## 4. 不配置 API 直接运行

无需 API Key 也能运行网站，并使用“可靠兜底”生成可追溯剧本骨架：

```powershell
.\scripts\start-demo.ps1
```

脚本启动成功后会自动打开：

```text
http://127.0.0.1:5173/
```

停止网站：

```powershell
.\scripts\stop-demo.ps1
```

## 5. 配置七牛 AI

### 5.1 准备 API Key

使用自己的七牛 AI 账号申请合法 API Key，并确认账号拥有可用文本模型。官方参考：

- [AI 大模型推理 API](https://developer.qiniu.com/aitokenapi/12882/ai-inference-api)
- [支持的模型列表](https://developer.qiniu.com/aitokenapi/12884/ai-model-list)

不要把 API Key 写入代码、README、Issue、PR、截图或 Demo 视频。

### 5.2 推荐方式：加密保存到当前电脑

在项目根目录执行：

```powershell
.\scripts\configure-qiniu.ps1 -Model deepseek-v3
```

PowerShell 会要求输入 API Key。输入时屏幕不会显示字符，这是正常的。配置会使用 Windows DPAPI 加密后保存到 Git 忽略的 `.local` 目录，只能由当前电脑的当前 Windows 用户解密。

如果要更换模型，再次运行命令并填写模型 ID：

```powershell
.\scripts\configure-qiniu.ps1 -Model qwen3-max
```

模型 ID 必须与网页从七牛读取到的列表完全一致。演示优先使用已经实际验收过的 `deepseek-v3`。

### 5.3 临时方式：只在当前 PowerShell 使用

不希望保存配置时，可以设置临时环境变量：

```powershell
$env:QINIU_AI_API_KEY="你的 API Key"
$env:QINIU_AI_MODEL="deepseek-v3"
.\scripts\start-demo.ps1
```

关闭这个 PowerShell 后，临时环境变量会失效。不要将真实 Key 保存到 `.env` 或提交到 Git。

## 6. 验证真实七牛调用

配置完成后运行：

```powershell
.\scripts\verify-qiniu.ps1 -Model deepseek-v3
```

成功时会显示：

```text
PASSED: real Qiniu AI generation completed.
quality_gate_passed=true
```

验收脚本会真实调用七牛 AI，并检查人物、地点、事件、场次、证据链与质量门禁，不会用兜底结果冒充 AI 成功。

## 7. 打开网站并完成一次生成

启动：

```powershell
.\scripts\start-demo.ps1
```

在网页中：

1. 粘贴或导入至少 3 章小说。
2. 点击“解析并检查”。
3. 选择“七牛 AI · 完整剧本化”或“可靠兜底”。
4. 七牛模式下选择模型和改编详略。
5. 点击生成按钮。
6. 查看场次与证据、故事要素、事件覆盖和交付检查。
7. 下载已通过剧本 YAML、验证包和 YAML Schema。

后端接口文档位于：

```text
http://127.0.0.1:8000/docs
```

## 8. 常见问题

### 提示前端依赖缺失

进入前端目录安装依赖：

```powershell
cd frontend
npm install
cd ..
```

### 提示 Demo PID file already exists

先停止旧服务，再重新启动：

```powershell
.\scripts\stop-demo.ps1
.\scripts\start-demo.ps1
```

### 网页显示七牛 AI 未配置

重新运行：

```powershell
.\scripts\configure-qiniu.ps1 -Model deepseek-v3
.\scripts\stop-demo.ps1
.\scripts\start-demo.ps1
```

然后在浏览器按 `Ctrl + F5` 强制刷新。

### 七牛模型超时或生成失败

- 优先使用 `deepseek-v3` 等已验证文本模型。
- 不要使用视觉模型处理纯文本小说。
- 根据页面给出的具体人物、地点、事件或场次诊断修复。
- 上游模型不稳定时可以重试，但不要把失败结果伪装为成功。

### 如何确认仓库没有泄露密钥

运行完整检查：

```powershell
.\scripts\check.ps1
```

看到 `No tracked secret material detected.` 表示已跟踪文件中未发现密钥材料。

## 9. 更新与卸载

获取主分支最新代码：

```powershell
git switch main
git pull --ff-only origin main
```

停止服务后，可以直接删除项目目录完成卸载。`.local` 中的加密七牛配置也会随项目目录删除。

