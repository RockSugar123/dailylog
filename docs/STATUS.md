# dailylog 状态（唯一维护的状态文档，新改动直接更新本文件）

> 约定：只维护这一个状态文档。每次会话结束时更新「当前状态」「遗留 / 注意事项」，
> 过程性记录压缩进「变更日志」。历史详情见 git log。

## 当前架构要点（截至 2026-08-25）

### 目录结构
- `core/`：业务模块（config / llm / analyze / capture / summarize / usage / todos）
  - 根目录只留入口与桥接：`app.py`（GUI 主程序）、`ui_api.py`（前端 API 桥接）
  - `core/config.py`：BASE_DIR = 源码根/exe 目录（定位代码），DATA_DIR = BASE_DIR 下 `data\` 子目录
  （运行数据）——开发版 `项目\data\`，打包版 `dailylog-app\data\`，构建镜像时排除
  - capture / usage / summarize 会被任务计划或命令行**直接运行**，文件头部有 sys.path 引导，
    内部一律用 `from core import X` 绝对导入
- `static/`：前端三件套 + 图标/字体。**改前端必须重跑 build.bat 才对打包版生效**
- 部署目录在项目外：`Desktop\dailylog-app\`（纯产物）；打包版数据在 `%LOCALAPPDATA%\dailylog`
- 任务计划开发模式命令由 `ui_api._task_command()` 生成，脚本路径指向 `core/capture.py`、`core/usage.py`
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
- **两套数据目录**：开发版在项目 `data\`，打包版在 `dailylog-app\data\`（都是 BASE_DIR 下 data 子目录）。
  排查数据问题先分清看的是哪一套
- `visibilitychange` 暂停 FX 依赖 WebView2 把隐藏窗口标记为 hidden，未逐项验证
- 改前端必须重跑 build.bat 部署到 `Desktop\dailylog-app` 才生效
- 换部署位置时三处同步：桌面快捷方式、任务计划 DailyLogCapture/DailyLogUsage、build.bat 的 DEPLOY_DIR
- 维护与打包约定见 `docs/MAINTENANCE.md`

## 变更日志（摘要）

### 2026-08-25 代码审查修复（db_stats / clear_data / get_report）
全量审查 Python 侧（app.py / ui_api.py / core/*），本轮修三处：
- **db_stats 日志统计路径错**：还在扫 BASE_DIR 的 dailylog.log*，日志实际在 DATA_DIR → 数据管理页日志条数/容量恒为 0，已改扫 DATA_DIR
- **clear_data 没删截图**（与 docstring 不符）：补删 SCREENSHOTS_DIR 下 *.png（返回结构不变）
- **get_report 路径穿越**：name 来自前端直接拼路径，可 ..\..\ 读任意文件；加 `re.fullmatch(r"[\w\-]+\.md", name)` 校验

审查发现但未修的遗留（按优先级）：
1. import_data 两处不一致：reports 文件名只 endswith(".md") 未挡穿越；合并设置只写盘不同步内存镜像（config.IDLE_ENABLED 等），导入后需重启才生效
2. 托盘回调访问未绑定的 window（app.py 托盘线程先于 window 赋值启动），启动瞬间点托盘会 NameError 被吞、点击无反应；建议线程启动前 `window = None`
3. _write_settings 非原子写，写一半崩溃 settings.json 损坏后全部设置静默回默认
4. todos.sync_from_records 无新增时不推进 last_synced_ts → 每次全量重扫当天 jsonl，线性变慢
5. task_next_run Interval 正则不识别 PT#H/组合格式（当前自建任务只会 PT#M，未触发）

### 2026-08-25 设置不生效修复 + 截图治理
- **设置改动即保存**（79fdd8c）：此前除皮肤外所有设置只在点"保存"时落盘，
  改完直接关窗/退出全部丢失（用户实测"重启后恢复原状"的根因）。
  截图间隔/自动暂停/记录保留/回车记录/应用时长/汇报人全部改为改动即落盘，保存按钮保留作汇总
- **"跳过重复画面"复选框此前漏绑 change 事件**，点了完全不生效，已补
- 设置页标签纠错："截图保留" → "记录保留"（该选项实际管时间线/日报/周报/应用时长的保留天数），
  加说明文字"截图始终用完即删"
- 截图即用即删确认：正常流程 finally 保证删除（capture.py）；新增兜底——cleanup_expired
  无条件清扫超 1 天的孤儿截图（进程强杀/崩溃残留，与保留天数设置无关）
- 清理 dailylog-app\data 里的历史残留（8 月 4 日的 4 张孤儿截图 + 旧日志）

### 2026-08-25 用户实测反馈四项修复
1. **手动截屏 HTTP 400**：NIM 报 "Request payload is too large"——4K 屏原始 PNG base64 超限。
   修复：`analyze.encode_image` 先 PIL 缩放（最长边 `ANALYZE_IMAGE_MAX_SIDE=1600`）再转 JPEG
   （质量 85），体积降一个数量级。已实测真实截屏成功入库
2. **手动截屏后最小化/最大化无响应**：`AppApi.manual_capture` 在 JS 桥线程同步跑截屏+LLM
   （含重试可达几十秒），阻塞所有窗口控制调用（✕ 是销毁窗口所以"看起来有反应"）。
   修复：改后台线程执行，完成后 evaluate_js 回推 toast；前端去掉过早的成功提示
3. **数据位置按用户要求调整**：frozen DATA_DIR 从 LOCALAPPDATA 改回部署目录旁，
   统一公式 `DATA_DIR = BASE_DIR / "data"`；build.bat 加回 `/XD data` 排除；
   数据已从 LOCALAPPDATA 迁到 `dailylog-app\data\`（LOCALAPPDATA 只留 webview 缓存）
4. **快捷方式空白图标**：lnk 显式设置 IconLocation 指向 exe + ie4uinit 刷新图标缓存
- 打包部署 + 启动验证通过

### 2026-08-25 数据/部署/源码三分离（根治打包事故类风险）
- `core/config.py` 新增 DATA_DIR（数据）与 BASE_DIR（代码定位）分离：
  开发版数据 → 项目 `data\`；frozen 数据最初放 `%LOCALAPPDATA%\dailylog`（同日按用户要求改为部署目录 data\）
- 全模块数据路径改走 DATA_DIR；`ui_api._task_command()` 仍用 BASE_DIR 定位脚本（语义正确）
- build.bat：部署目标改为项目外 `..\dailylog-app`；旧 `dist\` 已删除
- 数据迁移：开发数据移入 `data\`；dist 内 49 个记录文件 + .env/settings/state 等迁移核对一致后删 dist
- 桌面快捷方式、DailyLogCapture/DailyLogUsage 任务计划已指向新 exe 路径并启用
- 文档同步：MAINTENANCE.md 第 1/3/4 节重写、.gitignore 收敛为 data/ 一条

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
  node --check 过（已提交 5df8faf，黑猫图标见 55bcdf0）

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
