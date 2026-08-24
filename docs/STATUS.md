# dailylog 状态（唯一维护的状态文档，新改动直接更新本文件）

> 约定：只维护这一个状态文档。每次会话结束时更新「当前状态」「遗留 / 注意事项」，
> 过程性记录压缩进「变更日志」。历史详情见 git log。

## 当前架构要点（截至 2026-08-25）

### 目录结构
- `core/`：业务模块（config / llm / analyze / capture / summarize / usage / todos）
  - 根目录只留入口与桥接：`app.py`（GUI 主程序）、`ui_api.py`（前端 API 桥接）
  - `core/config.py` 的 `BASE_DIR`：frozen 时 = exe 所在目录；开发时 = 项目根（注意是 `.parent.parent`）
  - capture / usage / summarize 会被任务计划或命令行**直接运行**，文件头部有 sys.path 引导，
    内部一律用 `from core import X` 绝对导入
- `static/`：前端三件套 + 图标/字体。**改前端必须重跑 build.bat 才对打包版生效**
- 任务计划开发模式命令由 `ui_api._task_command()` 生成，脚本路径已指向 `core/capture.py`、`core/usage.py`
- 目录规范与新文件归属见 `docs/MAINTENANCE.md`

### 零窗口托盘化（2026-08-24 落地，内存 ~562MB → 关窗后 ~74MB）
- 主循环 `while not force_exit:` 建窗（hidden+pending_show）→ `webview.start()` 返回即置 `window=None`
  → `reopen.wait()` 挂起；托盘「打开程序」`reopen.set()` 唤醒；退出时也 set 以唤醒主循环退出
- pywebview 6.2.1 源码前提：窗口关闭会从全局 windows 移除，二次 create_window 复用 master uid；
  WinForms 初始化幂等；HTTP server 跨轮复用。**二次 `webview.start()` 属未文档化用法，
  pywebview 升级必须回归验证「关闭↔打开」循环**
- 旧「先建后删」方案已删除（browser/GPU 进程按 user-data-dir 共享导致全家桶常驻）

### 截屏分析接入前台窗口元数据（2026-08-24 落地）
- `usage.foreground_window()` 返回（进程名, 窗口标题）；capture 在 `_hide_app_windows()` **之前**采样；
  analyze 的 prompt 追加【当前前台窗口】块
- 隐私决策：进程名 + 标题只进 prompt 不落盘 jsonl（标题本来就在截图里可见，泄露面未增加）

## 内存优化遗留方案（按收益排序，均未实施）
1. **GPU 进程瘦身**（GPU ~300MB 是最大单项）：`--disable-gpu` 可砍大半但玻璃拟态 backdrop-filter 会卡；
   且 pywebview 6.2.1 把 AdditionalBrowserArguments 写死在 edgechromium.py:82，需 monkey-patch（升级易碎）
2. **隐藏时备用窗口导航 about:blank**：渲染进程 29 → ~15MB
3. **FX 引擎降载**：画布 DPR 上限 2 → 1、粒子数减半
4. 接受现状：显示 ~562MB 对 WebView2 GUI 属正常水平

## 遗留 / 注意事项
- **两套数据目录**：开发跑在项目根，打包版跑在 `dist\dailylog\`（frozen 后 BASE_DIR = exe 所在目录）。
  排查数据问题先分清看的是哪一套
- `visibilitychange` 暂停 FX 依赖 WebView2 把隐藏窗口标记为 hidden，未逐项验证
- 打包版静态文件在 `dist\dailylog\_internal\static`，改前端必须重跑 build.bat 才生效
- 维护与打包约定见 `docs/MAINTENANCE.md`
- **待办**：2026-08-25 的结构整理（core/ 分层 + 清理 + 文档）尚未提交 git，
  与 icon.ico 黑猫新图标改动一起提交；提交后需重跑 build.bat 部署新版

## 变更日志（摘要）

### 2026-08-25 项目结构整理（方案 B 分层）
- 7 个业务模块 git mv 进 `core/`（保留历史），根目录只留 app.py / ui_api.py；新增 `core/__init__.py`
- import 改造：包内一律 `from core import X` 绝对导入；capture / usage / summarize
  三个会被任务计划直接运行的入口加了 sys.path 引导（指向项目根，勿删）
- 关键适配：`core/config.py` 开发模式 BASE_DIR = `.parent.parent`；
  `ui_api._task_command()` 脚本路径改指 `core/`（ensure_usage_task 用 `/f` 覆盖，
  打包版不受影响走 frozen 分支）；dailylog.spec 无需改动（静态分析自动跟进 core 包）
- 删除：`.playwright-cli/`、`__pycache__/`、`build/`、`static/assets/backup/` + icon.ico.bak、
  `generated-images/`（图标源图）、过时的 plan.md、`static/assets/cat.ico`
  （与 icon.ico 哈希相同的无引用重复文件）
- 文档：两份 STATUS 合并为本文档；新建 `docs/MAINTENANCE.md`（目录规范 + 打包红线）；
  README 中英文版的目录树 / 命令表 / schtasks 示例同步 core/ 路径
- 验证：py_compile 全过、ui_api/app 导入正常、`python core\summarize.py --help` 正常、
  node --check 过。**未提交 git**；`static/assets/icon.ico` 有未提交的黑猫新图标修改，
  待确认后随本次改动一起提交

### 2026-08-24
- 零窗口托盘化落地并打包部署（详见上文架构要点）；修复专注时长浮点显示（fmtMin 取整）、
  皮肤回退（private_mode=False + 后端 theme 同步）、延迟导入截屏依赖（主进程 114 → 83MB）
- 截屏分析接入前台窗口元数据并部署；`.last_cleanup` 补进 build.bat robocopy 排除清单

### 2026-08-23
- UI 重构「总览优先」：新增今日总览页（环形图 + 指标卡 + 时间线预览 + Top5 + 待办速览），
  侧栏改图标竖栏；修 tooltip 遮挡 / 页面留白 / page-timeline 缺 hidden
- 皮肤扩到 8 个 + 统一 FX 引擎（每皮肤环境粒子 + 点击特效）+ 底部模糊色块；
  视觉提案 demo 在 `docs/skins-demo.html`

### 更早
- 2026-08-22 前：应用使用时长统计、待办管理、统一 LLM 通道（llm.py）、安全打包脚本 build.bat、
  自动截屏日志 + AI 日报周报（详见 git log）
