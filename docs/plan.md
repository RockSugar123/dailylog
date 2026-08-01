# dailylog 工作日志自动记录系统 — 实施计划

> 日期：2026-07-31 ｜ 状态：已与用户确认设计，开始实现

## 目标

每 10 分钟自动截屏 → 千问视觉模型分析 → 记录为按时间线排列的 Markdown 工作日志；鼠标空闲 ≥5 分钟自动暂停截屏；手动触发生成日报/周报，辅助周报写作。

## 架构

```
┌──────────────────────────────────────────────────────┐
│ Windows 任务计划程序（每 10 分钟触发一次）              │
│   capture.py：截屏 → 空闲检测 → 黑屏检测 → 去重        │
│              → 千问 qwen-vl 分析 → 写时间线 → 删截图   │
├──────────────────────────────────────────────────────┤
│ summarize.py（手动运行）                              │
│   读 raw 记录 → 千问文本模型 → 生成日报/周报 md         │
└──────────────────────────────────────────────────────┘
```

## 目录结构

```
dailylog/
├── .env                    # DASHSCOPE_API_KEY（用户自行填写）
├── requirements.txt        # mss / requests / python-dotenv
├── config.py               # 所有可调参数集中
├── capture.py              # 入口：截屏 → 分析 → 记录（任务计划调用）
├── analyze.py              # 千问 API 调用 + 宽容 JSON 解析 + 分析 prompt
├── summarize.py            # 手动：--day / --week 生成日报周报
├── state.json              # 运行时生成：上张截图哈希（去重用）
├── records/
│   ├── YYYY-MM-DD.md       # 每日时间线（最终产物）
│   └── raw/YYYY-MM-DD.jsonl# 结构化原始记录（总结聚合用）
├── reports/                # 生成的日报/周报
└── screenshots/            # 临时截屏，分析后立即删除
```

## 单次运行流程（capture.py）

```
1. 未配置 API key → 报错退出
2. 鼠标空闲检测（GetLastInputInfo ≥ 5 分钟）→ 跳过，退出
3. mss 截主屏（monitors[1]）
4. 黑屏检测（亮度采样 >99% 全黑）→ 跳过，退出
5. 去重（md5(原始buffer) == state.json 上张哈希）→ 跳过，退出
6. 截图存临时 PNG → base64 → 千问 qwen-vl-plus 分析
7. 解析 JSON（response_format 优先，失败宽容提取 {…} 块）
8. 写入当日 records/YYYY-MM-DD.md + raw jsonl
9. 删除临时截图（即用即删，磁盘不保留原始画面）
```

失败处理：API 失败重试 1 次（间隔 3s）→ 仍失败写 `⚠️ 分析失败` 占位条目，且**不更新哈希** → 下个 tick 自动重试。

## 时间线 Markdown 格式

```markdown
# 2026-07-31 工作日志

## 09:10 · 代码开发
修复登录接口 token 过期处理 bug，涉及认证模块和请求拦截逻辑（VS Code）。
进展：本地验证通过，待提交 | 待办：补充超时重试的单元测试

## 10:22 · 需求沟通
正在处理 iOS 原生 App 原型设计相关任务，整理任务清单与排期。
```

活动分类 → 中文标签映射（config.py 可改）：coding=代码开发、writing=文档写作、meeting=会议、research=资料研究、communication=沟通交流、data=数据分析、support=客户支持、browsing=网页浏览、idle=空闲、other=其他。

## API 接入

- Endpoint：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`（OpenAI 兼容）
- 分析模型：`qwen3.5-omni-plus-2026-03-15`（视觉，阿里云百炼）
- 总结模型：`deepseek-v4-flash`（文本，DeepSeek 官方 API api.deepseek.com）
- Key 来源：阿里百炼控制台（bailian.console.aliyun.com）+ DeepSeek 平台（platform.deepseek.com），填入 `.env`

## 成本（含去重）

8h 工作 ≈ 48 次采样，去重后 15~25 条有效；视觉模型 ≈ ¥1.5~3/百万 token，单张 1080p 截图 ≈ 1000~2000 token → 单次 ≈ 0.003~0.01 元，**每天 < 0.2 元**。新账户有免费额度。

## 隐私设计

1. **即用即删**：截图只在内存→临时文件→API 过程中存在，分析完立即删除，磁盘不保留原始画面
2. **输出脱敏**：分析 prompt 强制 AI 输出时替换身份信息/敏感字段（占位符），只保留脱敏后的工作事项
3. **边界说明**：截图明文会上传阿里云服务器，prompt 只防"输出"泄露；如需防"输入"泄露需 V2 本地模糊处理
4. 明确不记录：私人聊天细节、联系人身份、账号、密钥、完整链接、薪酬绩效、财务明细

## 任务计划注册（Windows）

```bash
# pythonw 无控制台窗口运行；/f 覆盖已存在任务
schtasks /create /tn "DailyLogCapture" /tr "\"<pythonw全路径>\" c:\Users\ASUS\Desktop\dailylog\capture.py" /sc minute /mo 10 /f
schtasks /run /tn DailyLogCapture   # 手动触发一次（冒烟测试）
schtasks /delete /tn DailyLogCapture /f   # 卸载
```

## 实现步骤与验证

| # | 步骤 | 验证 |
|---|------|------|
| 1 | 创建项目骨架与全部代码 | `python -m py_compile` 全部通过 |
| 2 | 逻辑单元验证 | parse_json 正常/异常输入、render_entry 格式、黑屏检测合成数据 |
| 3 | 无 key 冒烟 | 运行 capture.py 干净退出并提示配置 key |
| 4 | 注册任务计划 | `schtasks /query` 能看到任务 |
| 5 | 用户填 key 后 | 手动跑一次 capture.py → records 出现时间线条目 |
| 6 | 总结验证 | `python summarize.py --day <日期>` 生成日报 |

## 风险与边界

- 10 分钟粒度 + 空闲恢复最多延迟 10 分钟（不引入守护进程，若需要"鼠标一动立即恢复"再升级）
- qwen-vl-plus 的 response_format json_object 若不支持，宽容解析兜底
- 截屏失败/无显示器 → 异常捕获后退出，不产生脏数据
