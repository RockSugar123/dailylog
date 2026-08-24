# dailylog · 今日轨迹

**简体中文** | [English](README.en.md)

<div align="center">

![dailylog](docs/images/overview.png)

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)
![Stars](https://img.shields.io/github/stars/RockSugar123/dailylog?style=social)

**自动记录一天的工作时间线，一键生成日报/周报。**

每 10 分钟截屏一次，由视觉模型把屏幕画面转成结构化工作记录，DeepSeek 再基于记录生成可交付的日报/周报。

[功能特性](#-功能特性) · [界面预览](#-界面预览) · [技术栈](#-技术栈) · [快速开始](#-快速开始) · [隐私设计](#-隐私设计)

</div>

## 📖 作者的话

这个工具是闲暇时随手开发的，用于测试 deepseek v4 最新模型。这只是一个小玩具，但是足以满足日常办公的记录和日报周报的总结。模型可以自己配置，不会的用 ai 帮你配，便宜好用的就行，不一定要跟作者一样选择这两个，作者选这两个主要是免费便宜。

在这里，作者唠叨两句，在下载任何一个项目时一定一定要审查代码安全。不要暴露自己的 key。

## ✨ 功能特性

- **自动记录**：Windows 任务计划程序每 10 分钟驱动一次截屏分析，无需常驻进程
- **智能跳过**：鼠标键盘静止（默认 ≥5 分钟）暂停、黑屏/睡眠跳过、画面去重（md5 比对）
- **手动截屏**：设置页按钮，5 秒倒计时后截取当前屏幕并记录；截屏瞬间自动隐藏应用自身窗口，界面不会进入截图
- **时间线浏览**：按日/周/月查看活动轨迹、分类时长分布、专注时长估算
- **应用时长统计**：前台进程采样，按日/周/月聚合各应用使用时长
- **待办管理**：从工作记录中提取待办，支持优先级与完成状态跟踪
- **一键报告**：基于时间线记录生成日报（成果导向模板）与周报（按项目归类），Markdown 直接可用
- **隐私设计**：截图即用即删、输出强制脱敏（见 [隐私设计](#-隐私设计)）
- **托盘常驻**：关闭窗口最小化到托盘，记录持续运行；打包为单文件 exe 后可全自动运行

## 🖼 界面预览

| 总览 | 活动线 |
|------|--------|
| ![总览](docs/images/overview.png) | ![活动线](docs/images/timeline.png) |

| 应用时长 | 待办 |
|----------|------|
| ![应用时长](docs/images/app-usage.png) | ![待办](docs/images/todos.png) |

| 设置 |
|------|
| ![设置](docs/images/settings.png) |

## 🛠 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.10+ |
| 桌面 GUI | [pywebview](https://pywebview.flowrl.com/)（WebView2 无边框窗口）+ 原生 HTML/CSS/JS 前端 |
| 系统托盘 | pystray + pywin32 |
| 屏幕截取 | mss + Pillow |
| 空闲检测 | pywin32（GetLastInputInfo）+ pynput |
| LLM 调用 | requests → NVIDIA NIM（视觉模型分析截图）+ DeepSeek（生成日报/周报） |
| 定时调度 | Windows 任务计划程序（schtasks） |
| 配置管理 | python-dotenv（`.env`）+ settings.json |
| 打包分发 | PyInstaller（onedir 模式） |

## 🚀 快速开始

### 环境要求

- Windows 10/11（任务计划 + mss 截屏 + GetLastInputInfo 均为 Windows 能力）
- Python 3.10+（开发验证环境 3.13）
- 两个 API Key：
  - **NVIDIA NIM**（截图分析，视觉模型，默认 `minimaxai/minimax-m3`）：<https://build.nvidia.com>
  - **DeepSeek 官方**（日报/周报总结）：<https://platform.deepseek.com>

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

按 [.env.example](.env.example) 的键名填写（开发期放源码目录，打包后放 exe 同目录——打包版只读 exe 旁边的 .env）：

```
ANALYZE_API_KEY=你的NVIDIA Key
DEEPSEEK_API_KEY=sk-你的DeepSeekKey
```

### 3. 启动

```bash
python app.py
```

应用启动时会自动注册 Windows 定时任务 `DailyLogCapture`（每 10 分钟截屏记录一次，UI 可开关）。关闭窗口会最小化到托盘，记录持续运行。

### 命令行用法

| 用途 | 命令 |
|------|------|
| 桌面应用（推荐） | `python app.py` |
| 仅截屏记录（无界面，任务计划调用） | `pythonw capture.py` |
| 生成今天的日报 | `python summarize.py` |
| 生成某日日报 | `python summarize.py --day 2026-07-31` |
| 生成某周周报（该日期所在 ISO 周） | `python summarize.py --week 2026-07-31` |
| 打包版桌面应用 | `dist\dailylog\dailylog.exe` |
| 打包版截屏记录 | `dist\dailylog\dailylog.exe --capture` |
| 打包诊断（打印任务计划/配置状态） | `dist\dailylog\dailylog.exe --diag` |

### 注册 Windows 定时任务（可选，应用启动时会自动注册）

```bash
# 开发期（pythonw 无控制台窗口；/f 覆盖已存在任务）
schtasks /create /tn DailyLogCapture /tr "\"<pythonw全路径>\" <项目绝对路径>\capture.py" /sc minute /mo 10 /f

# 打包后（onedir，exe 在 dist\dailylog\ 下）
schtasks /create /tn DailyLogCapture /tr "\"C:\path\to\dist\dailylog\dailylog.exe\" --capture" /sc minute /mo 10 /f

schtasks /run /tn DailyLogCapture    # 手动触发一次（冒烟测试）
schtasks /delete /tn DailyLogCapture /f   # 卸载
```

## ⚙️ 工作原理

```
┌──────────────────────────── 定时任务 DailyLogCapture（每 10 分钟） ────────────────────────────┐
│  capture.py：空闲检测 → mss 截屏 → 黑屏检测 → 去重 → 视觉模型分析 → 写时间线 → 删截图         │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
        │ 写入
        ▼
  records/YYYY-MM-DD.md（人类可读时间线） + records/raw/YYYY-MM-DD.jsonl（结构化原始记录）
        │
        ▼ 手动触发（UI 按钮 / CLI）
  summarize.py：聚合记录 → DeepSeek → reports/日报-YYYY-MM-DD.md / 周报-YYYY-Www.md
```

## 🔧 设置项

通过应用「设置」页修改，持久化到 `settings.json`：

| 键 | 说明 | 可选值 | 默认 |
|----|------|--------|------|
| `interval_minutes` | 截屏间隔 | 5 / 10 / 15 / 30 / 60 | 10 |
| `recording_enabled` | 定时记录总开关（标题栏/托盘切换时持久化，启动时恢复） | true / false | true |
| `idle_enabled` | 鼠标静止时暂停截屏 | true / false | true |
| `idle_minutes` | 空闲阈值 | 1 / 2 / 5 / 10 / 15 / 20 / 30 | 5 |
| `report_name` | 日报"汇报人"，留空不输出该行 | 任意文本 | "" |
| `retention_days` | 本地记录保留天数，过期自动清理（0 = 永久保留） | 0 / 7 / 14 / 30 / 60 / 90 | 0 |
| `test_interval_seconds` | 测试用秒级截屏间隔（设置页改回分钟即清除，勿在生产使用） | 任意秒数 | 无 |

数据清理规则：`retention_days` 非 0 时，应用启动与每次截屏时检查（每天最多一次），删除日期早于窗口的 `records/` 记录与 `reports/` 日报/周报（周报按周日算边界，覆盖到窗口内不删）；文件名无法解析的报告不删。节流标记存 `.last_cleanup`。

手动截屏（设置页按钮）强制记录：跳过空闲检测与画面去重，适合开会、演示等需要记录的瞬间。所有截屏（定时与手动）在抓屏前自动隐藏应用窗口，保存后立即恢复。

## 📦 数据产物

### 时间线 `records/YYYY-MM-DD.md`

```markdown
# 2026-07-31 工作日志

## 09:10 · 开发
修复登录接口 token 过期处理 bug，涉及认证模块和请求拦截逻辑（VS Code）。
进展：本地验证通过，待提交 | 待办：补充超时重试的单元测试
```

### 原始记录 `records/raw/YYYY-MM-DD.jsonl`

每行一条 JSON：

```json
{"ts": "2026-07-31T09:10:00", "activity": "coding", "summary": "…",
 "detail": "…", "progress": "…", "todo": "…", "apps": ["VS Code"], "contains_sensitive": false}
```

- `activity` 分类：`coding`开发 / `writing`文档 / `meeting`会议 / `research`学习 / `communication`沟通 / `data`数据分析 / `support`运维 / `browsing`生活 / `idle`空闲 / `other`其他（[config.py](config.py) 可改标签）
- `contains_sensitive`：该条涉及敏感内容（已脱敏）

### 报告 `reports/`

- 日报：`日报-YYYY-MM-DD.md`（成果导向模板：核心成果 / 关键指标 / 重点事项 / 风险阻塞 / 明日三件事）
- 周报：`周报-YYYY-Www.md`（按项目/主题归类，附时间分布、遗留问题、下周建议）

## 🔒 隐私设计

1. **即用即删**：截图只在内存 → 临时文件 → API 分析过程中存在，分析完立即删除，磁盘不保留原始画面
2. **输出脱敏**：分析 prompt 强制模型输出时替换联系人身份、账号、密钥、完整链接等敏感字段，只保留脱敏后的工作事项
3. **边界说明**：截图明文会上传所选模型服务端，脱敏规则只约束"输出"不约束"输入"；若需输入侧保护需自行扩展本地模糊处理
4. 时间线记录仅保存在本机 dailylog 目录

## 💰 成本估算（含去重）

8h 工作 ≈ 48 次采样，去重后 15~25 条有效。费用与所选模型强相关：默认 `minimaxai/minimax-m3`（NVIDIA NIM，个人账户有免费额度），请以所选模型的输入/输出单价实测。

## 📦 目录结构

<details>
<summary>展开查看</summary>

```
dailylog/
├── .env                    # 两个 API Key（用户自行填写，勿随包分发）
├── requirements.txt        # mss / requests / python-dotenv / pywebview / pywin32 / pystray / pillow / pynput
├── config.py               # 全部可调参数集中（API、间隔、目录、分类标签）
├── capture.py              # 截屏记录入口（任务计划调用）
├── analyze.py              # 视觉模型调用（config.ANALYZE_MODEL 可换）+ 宽容 JSON 解析 + 分析 prompt
├── summarize.py            # DeepSeek 日报/周报生成（CLI：--day / --week）
├── ui_api.py               # 桌面应用 API 桥：时间线/报告/设置/任务计划管理（纯 Python，可无 GUI 直测）
├── app.py                  # 桌面应用入口：pywebview 无边框窗口 + pystray 托盘
├── dailylog.spec           # PyInstaller 打包配置（onedir）
├── settings.json           # 运行时设置（开发版；UI 可改）
├── state.json              # 运行时状态（开发版；上张截图哈希，去重用）
├── .last_cleanup           # 数据清理节流标记（当天已清理则跳过，存日期字符串）
├── records/                # 开发版时间线记录（raw/YYYY-MM-DD.jsonl + YYYY-MM-DD.md）
├── reports/                # 开发版生成的日报/周报
├── static/                 # 前端（index.html / style.css / script.js）
├── docs/                   # 文档与说明图（images/）
└── dist/
    └── dailylog/           # 打包版（onedir）：exe + _internal/ 依赖库
        ├── dailylog.exe    # 打包版可执行文件（数据与 exe 同目录）
        ├── _internal/      # 打包依赖库（勿动）
        ├── .env            # 打包版 API Key（勿随包分发）
        ├── settings.json   # 打包版运行时设置（UI 可改）
        ├── state.json      # 打包版运行时状态
        ├── .last_cleanup   # 数据清理节流标记
        ├── records/        # 打包版时间线记录（最终产物）
        ├── reports/        # 打包版日报/周报
        └── dailylog.log    # 打包版运行日志
```

> **数据位置**：打包版与开发版各自独立——打包版数据在 `dist/dailylog/`（exe 同目录），开发版数据在项目根目录。

</details>

## 🧑‍💻 开发与打包

```bash
build.bat                 # 推荐：安全打包（产物先出临时目录再部署，不碰运行数据）
pyinstaller dailylog.spec # 注意：onedir 模式会清空重建输出目录！
```

**重要**：PyInstaller onedir 打包会**清空重建输出目录**。`dailylog.spec` 未指定 distpath 时输出到 `dist/dailylog/`——若直接打包会删掉里面的运行数据（`.env`、`records/` 等）。**务必使用 `build.bat`**（打包到临时目录 `dist_build/` 后用 `/MIR` 镜像部署，显式排除数据文件/目录）。

其他注意：

- onedir 模式：桌面应用/截屏记录/诊断都指向 `dist\dailylog\dailylog.exe`；数据在 **exe 同目录**（`.env`、`settings.json`、`records/`、`reports/`），不要把含密钥的 `dist\dailylog\.env` 随包分发
- 打包环境需额外安装 pyinstaller
- WebView2 数据目录固定在 `%LOCALAPPDATA%\dailylog\webview`（避免每次启动新建临时目录）；历史残留由应用启动时自动清理

## 🩺 故障排查

- **所有运行日志**：`dailylog.log`（1MB 轮转保留 3 份），与源码/exe 同目录
- **任务计划未生效**：设置页「当前状态」会显示"已停用"；用 `schtasks /query /tn DailyLogCapture` 检查
- **API 报错**：错误会带响应体前 300 字符写入日志，便于定位（如 400 模型名/Key 错误）
- **测试秒级记录**：设置页或 `apply_test_interval` 写入 `test_interval_seconds` 后，应用内自动进入测试循环（任务计划 schema 限制最小 1 分钟，秒级只能由应用进程驱动）
- **分析失败占位**：失败会写入"分析失败，下轮自动重试"占位条目，并标记重试状态——下个周期即使画面未变也会自动重试（避免连续失败时占位条目堆积）

## ⚠️ 已知限制

- 10 分钟粒度：空闲恢复最多延迟一个周期（不引入守护进程）
- 时长统计（专注时长、分类分布）按记录间隔**估算**，非精确计量
- 截屏明文上传云端：prompt 只防"输出"泄露，不防"输入"

## 📄 许可证

[MIT](LICENSE)

---

**简体中文** | [English](README.en.md)
