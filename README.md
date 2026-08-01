# dailylog · 今日轨迹

自动记录一天的工作时间线，一键生成日报/周报。每 10 分钟截屏一次，由视觉模型把屏幕画面转成结构化工作记录，DeepSeek 再基于记录生成可交付的日报/周报。


## 作者的话
  这个工具是闲暇时随手开发的，用于测试deepseekv4最新模型。这只是一个小玩具，但是足以满足日常办公的记录和日报周报的总结。模型可以自己配置，不会的用ai帮你配，便宜好用的就行，不一定要跟作者一样选择这两个，作者选这两个主要是免费便宜。

  在这里，作者唠叨两句，在下载任何一个项目时一定一定要审查代码安全。不要暴露自己的key。

## 功能特性

- **自动记录**：Windows 任务计划程序每 10 分钟驱动一次截屏分析，无需常驻进程
- **智能跳过**：鼠标键盘静止（默认 ≥5 分钟）暂停、黑屏/睡眠跳过、画面去重（md5 比对）
- **时间线浏览**：暗色玻璃风格桌面应用，按日/周/月查看活动轨迹、分类时长分布、专注时长估算
- **一键报告**：基于时间线记录生成日报（成果导向模板）与周报（按项目归类），Markdown 直接可用
- **隐私设计**：截图即用即删、输出强制脱敏（见 [隐私设计](#隐私设计)）
- **托盘常驻**：关闭窗口最小化到托盘，记录持续运行；打包为单文件 exe 后可全自动运行

## 工作原理

```
┌──────────────────────────── 定时任务 DailyLogCapture（每 10 分钟） ────────────────────────────┐
│  capture.py：空闲检测 → mss 截屏 → 黑屏检测 → 去重 → 千问视觉模型分析 → 写时间线 → 删截图        │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
        │ 写入
        ▼
  records/YYYY-MM-DD.md（人类可读时间线） + records/raw/YYYY-MM-DD.jsonl（结构化原始记录）
        │
        ▼ 手动触发（UI 按钮 / CLI）
  summarize.py：聚合记录 → DeepSeek → reports/日报-YYYY-MM-DD.md / 周报-YYYY-Www.md
```

## 目录结构

```
dailylog/
├── .env                    # 两个 API Key（用户自行填写，勿随包分发）
├── requirements.txt        # mss / requests / python-dotenv / pywebview / pywin32 / pystray / pillow
├── config.py               # 全部可调参数集中（API、间隔、目录、分类标签）
├── capture.py              # 截屏记录入口（任务计划调用）
├── analyze.py              # 千问视觉模型调用 + 宽容 JSON 解析 + 分析 prompt
├── summarize.py            # DeepSeek 日报/周报生成（CLI：--day / --week）
├── ui_api.py               # 桌面应用 API 桥：时间线/报告/设置/任务计划管理（纯 Python，可无 GUI 直测）
├── app.py                  # 桌面应用入口：pywebview 无边框窗口 + pystray 托盘
├── dailylog.spec           # PyInstaller 打包配置
├── settings.json           # 运行时设置（UI 可改）
├── state.json              # 运行时状态（上张截图哈希，去重用）
├── records/
│   ├── YYYY-MM-DD.md       # 每日时间线（最终产物）
│   └── raw/YYYY-MM-DD.jsonl# 结构化原始记录（总结聚合用）
├── reports/                # 生成的日报/周报
├── screenshots/            # 临时截屏目录（分析后立即删除）
├── static/                 # 前端（index.html / style.css / script.js）
└── docs/plan.md            # 原始实施计划
```

## 环境要求

- Windows 10/11（任务计划 + mss 截屏 + GetLastInputInfo 均为 Windows 能力）
- Python 3.10+（开发验证环境 3.13）
- 两个 API Key：
  - **阿里云百炼**（截图分析，视觉模型）：<https://bailian.console.aliyun.com>
  - **DeepSeek 官方**（日报/周报总结）：<https://platform.deepseek.com>

## 安装与配置

```bash
pip install -r requirements.txt
```

按 [.env.example](.env.example) 的键名填写（开发期放源码目录，打包后放 exe 同目录——打包版只读 exe 旁边的 .env）：

```
DASHSCOPE_API_KEY=sk-你的百炼Key
DEEPSEEK_API_KEY=sk-你的DeepSeekKey
```

## 运行方式

| 用途 | 命令 |
|------|------|
| 桌面应用（推荐） | `python app.py` |
| 仅截屏记录（无界面，任务计划调用） | `pythonw capture.py` |
| 生成今天的日报 | `python summarize.py` |
| 生成某日日报 | `python summarize.py --day 2026-07-31` |
| 生成某周周报（该日期所在 ISO 周） | `python summarize.py --week 2026-07-31` |
| 打包版桌面应用 | `dailylog.exe` |
| 打包版截屏记录 | `dailylog.exe --capture` |
| 打包诊断（打印任务计划/配置状态） | `dailylog.exe --diag` |

### 注册 Windows 定时任务

桌面应用启动时会自动启用任务 `DailyLogCapture`（UI 可开关）；也可手动注册：

```bash
# 开发期（pythonw 无控制台窗口；/f 覆盖已存在任务）
schtasks /create /tn DailyLogCapture /tr "\"<pythonw全路径>\" c:\Users\ASUS\Desktop\dailylog\capture.py" /sc minute /mo 10 /f

# 打包后
schtasks /create /tn DailyLogCapture /tr "\"<exe全路径>\" --capture" /sc minute /mo 10 /f

schtasks /run /tn DailyLogCapture    # 手动触发一次（冒烟测试）
schtasks /delete /tn DailyLogCapture /f   # 卸载
```

## 设置项

通过应用「设置」页修改，持久化到 `settings.json`：

| 键 | 说明 | 可选值 | 默认 |
|----|------|--------|------|
| `interval_minutes` | 截屏间隔 | 5 / 10 / 15 / 30 / 60 | 10 |
| `idle_enabled` | 鼠标静止时暂停截屏 | true / false | true |
| `idle_minutes` | 空闲阈值 | 1 / 2 / 5 / 10 / 15 / 20 / 30 | 5 |
| `report_name` | 日报"汇报人"，留空不输出该行 | 任意文本 | "" |
| `test_interval_seconds` | 测试用秒级截屏间隔（设置页改回分钟即清除，勿在生产使用） | 任意秒数 | 无 |

## 数据产物

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

## 隐私设计

1. **即用即删**：截图只在内存 → 临时文件 → API 分析过程中存在，分析完立即删除，磁盘不保留原始画面
2. **输出脱敏**：分析 prompt 强制模型输出时替换联系人身份、账号、密钥、完整链接等敏感字段，只保留脱敏后的工作事项
3. **边界说明**：截图明文会上传阿里云百炼服务端，脱敏规则只约束"输出"不约束"输入"；若需输入侧保护需自行扩展本地模糊处理
4. 时间线记录仅保存在本机 dailylog 目录

## 成本估算（含去重）

8h 工作 ≈ 48 次采样，去重后 15~25 条有效；视觉模型单张 1080p 截图 ≈ 1000~2000 token，单次 ≈ 0.003~0.01 元，**每天 < 0.2 元**（新账户有免费额度）。

## 开发与打包

```bash
pyinstaller dailylog.spec   # 产物在 dist/dailylog.exe
```

注意：

- 打包后 `.env`、`settings.json`、`records/`、`reports/` 都在 **exe 同目录** 生成，不要把含密钥的 `dist/.env` 随包分发
- 打包环境需额外安装 pyinstaller

## 故障排查

- **所有运行日志**：`dailylog.log`（1MB 轮转保留 3 份），与源码/exe 同目录
- **任务计划未生效**：设置页「当前状态」会显示"已停用"；用 `schtasks /query /tn DailyLogCapture` 检查
- **API 报错**：错误会带响应体前 300 字符写入日志，便于定位（如 400 模型名/Key 错误）
- **测试秒级记录**：设置页或 `apply_test_interval` 写入 `test_interval_seconds` 后，应用内自动进入测试循环（任务计划 schema 限制最小 1 分钟，秒级只能由应用进程驱动）
- **分析失败占位**：失败会写入"分析失败，下轮自动重试"占位条目，并标记重试状态——下个周期即使画面未变也会自动重试（避免连续失败时占位条目堆积）

## 已知限制

- 10 分钟粒度：空闲恢复最多延迟一个周期（不引入守护进程）
- 时长统计（专注时长、分类分布）按记录间隔**估算**，非精确计量
- 截屏明文上传云端：prompt 只防"输出"泄露，不防"输入"
