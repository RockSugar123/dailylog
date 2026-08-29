# dailylog 状态（唯一维护的状态文档，新改动直接更新本文件）

> 约定：只维护这一个状态文档。每次会话结束时更新「当前状态」「遗留 / 注意事项」，
> 过程性记录压缩进「变更日志」。历史详情见 git log。

## 当前架构要点（截至 2026-08-29）

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

### 画面感知去重（2026-08-29 落地）
- 原「跳过重复画面」用整屏原始字节 md5 全等：任务栏时钟（10 分钟档必跳分钟位）、
  光标移动都会击穿，生产 58 次成功 0 次跳过，去重形同虚设
- 改为感知签名：裁掉任务栏（SPI_GETWORKAREA，仅原点主屏适用）→ 32×32 灰度图存
  `state.json` 的 `last_sig`（base64，跨进程持久化），比对 dHash 汉明距离（阈值
  `DEDUP_HASH_BITS=12`）或平均像素差（`DEDUP_PIXEL_DIFF=1.5`）任一超阈即视为变化
- 阈值实测依据：静态底噪 ≤8 位（视频窗口微动），最小真实变化（角落通知）17 位；
  未裁到任务栏时时钟跳变仅 1 位，阈值兜底有效
- `last_failed`（上轮分析失败）仍放行重试；手动截屏 force 仍跳过去重；
  旧 `last_hash` 首轮自动迁移（多记录一次）

### 统一模型服务（2026-08-29 落地，同日晚补自定义双模型）
- `config.MODEL_PRESETS`：预设供应商表（官方 OpenAI 兼容 base_url 代码内置，用户改不了）；
  当前生效供应商 = `settings.json` 的 `model_provider`。预设供应商下截图分析与日报生成
  **共用一个模型**；`custom`（自定义）为双模型模式：分析走 `model_services["custom"]`
  （Key: `MODEL_KEY_CUSTOM`），总结走 `summary_services["custom"]`（Key: `MODEL_KEY_SUMMARY`），
  完全手填无任何模型预置，未配全时 capture/summarize 给"去设置页填写"提示
- `_apply_model_service()` 把当前供应商解析进模块变量并经 `ANALYZE_*`/`DEEPSEEK_*`
  别名暴露（analyze.py/summarize.py 与任务计划独立进程零改动）；
  `ui_api.save_model_service` 保存后调用它 + 同步 `os.environ`
  （`.env` 只在启动时 load_dotenv，进程内保存必须补环境变量）
- Key 解析链在 `config.model_key_for()` / `config.summary_key()`：
  `MODEL_KEY_<供应商ID大写>` → 旧键按归属回退（dashscope/custom ← ANALYZE_API_KEY、
  deepseek/总结 ← DEEPSEEK_API_KEY）；settings 未记录供应商时 `_default_provider()`
  按 `nvapi-` 前缀默认进自定义，否则 dashscope

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
- 默认模型有时效性：供应商下架/更名后改 `config.MODEL_PRESETS` 的 `default_model` 即可
  （用户已保存的 model_services 不受影响）
- 新增预设供应商的前提：OpenAI 兼容端点 + 支持多模态视觉输入（截图分析需要）
- 海外端点（如 NVIDIA NIM）直连受跨境波动影响：`llm._post_chat` 直连优先，
  连接级失败自动经系统代理重试一次并按端点记忆（进程内）——国内端点行为不变；
  代理工具需在线，否则海外端点不可用（报错已提示）

## 变更日志（摘要）

### 2026-08-29 画面感知去重 + 自定义双模型 + 代理自动回退
- **去重失效修复**：整屏 md5 被任务栏时钟/光标击穿（生产 58 成功 0 跳过），
  改感知签名（见架构要点「画面感知去重」）；state.json `last_hash` → `last_sig` 自动迁移
- **自定义双模型**：custom 拆「截图分析 / 报告总结」两组端点/模型/Key 独立配置
  （settings.json 新增 `summary_services`，Key `MODEL_KEY_SUMMARY`）；
  自定义无任何模型预置（个人配置不进代码），两组保存必填校验；
  `nvapi-` 旧键自动进自定义模式；UI 分组表单 + 两组独立测试连接
- **llm.py 代理自动回退**：直连优先，连接级失败经系统代理重试一次（按端点
  进程内记忆）；超时/429 报错友好化。历史日志佐证：5 天 58 成功 0 连接超时，
  直连常态可用，回退仅兜波动窗口（9×429 为 NIM 免费档限流，与代理无关）
- 文档同步：README 中英文去重描述、analyze/summarize/关于弹窗的 NIM 残留文案清理；
  build.bat 重新打包部署验证（生产 16:52 起连续成功）

### 2026-08-29 模型服务重构：预设供应商下拉（4426373）
- 设置页模型服务面板：原「截图分析 / 日报总结」双 Key 改为**预设供应商下拉**
  （千问/智谱/OpenAI/Kimi/硅基流动/豆包/DeepSeek/自定义），官方 OpenAI 兼容端点
  内置 `config.MODEL_PRESETS`，用户只填模型名称 + Key
- **按供应商独立记忆**：模型名存 `settings.json` 的 `model_services`
  （{pid: {model, base_url?}}），Key 存 `.env` 的 `MODEL_KEY_<供应商ID大写>`；
  切换下拉即时联动回显，未保存过为空白
- 截图分析与日报生成**统一走当前生效供应商**（预设均多模态）；config 经
  `ANALYZE_*`/`DEEPSEEK_*` 别名兼容 analyze.py/summarize.py 及任务计划独立进程，
  无需改调用点
- 旧 Key 按归属回退：`ANALYZE_API_KEY`→千问、`DEEPSEEK_API_KEY`→DeepSeek
  （旧统一键 `MODEL_API_KEY` 仅作千问回退，保存时自动清理旧版统一键）
- 默认模型均为 2026-08 核实的在售多模态型号：`glm-5.3-flash`/`gpt-5-mini`/
  `kimi-k3`/`Qwen3-VL-32B`/`doubao-seed-1-6-vision-250815`/`deepseek-v4-flash-vision-exp`
- 前端 API 替换：`get_model_service`/`save_model_service`/`test_model_connection`
  （测试按表单草稿、Key 留空回退已存值）替代旧的双 Key 三接口；
  导出白名单加 `model_services`（Key 照旧永不进备份）
- fix：采样常量 `ANALYZE_TEMPERATURE/TOP_P/MAX_TOKENS` 重构时误置函数内，
  模块属性缺失致截屏分析全量报 AttributeError，已挪回模块级

### 2026-08-25 新功能：生成指定日期的日报（fe718d7）
- 日报周报页新增日期选择器 + 「生成该日日报」按钮（默认今天；校验非空、不允许未来日期）
- 后端 `ui_api.generate_report(kind, date)` 原本就支持任意日期，本次纯前端入口改动
- 端到端验证：用 8 月 4 日记录真实生成日报成功（DeepSeek 成果导向模板）；
  无记录日期返回"该日无任何记录"

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
