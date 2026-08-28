# dailylog 维护指南

> 写给下一个开发者。读完这页，你就知道每类文件该放哪、哪些目录碰不得、打包怎么跑。
> 项目当前状态与架构决策见 [STATUS.md](STATUS.md)，本页只讲"怎么维护"。

## 1. 目录结构总览

```
dailylog/                     # 源码仓库：只放代码和文档，不含任何运行数据
├── app.py              # GUI 主程序入口（pywebview 窗口 + pystray 托盘）
├── ui_api.py           # 前端 API 桥接层（前端所有可调用的后端方法都在这，纯 Python 可无 GUI 直测）
├── core/               # 全部业务模块（Python 包）
│   ├── config.py       # 参数中心：API、间隔、路径、分类标签。改配置先来这里
│   ├── capture.py      # 截屏→分析→写时间线（任务计划调用；也可直接运行）
│   ├── usage.py        # 应用使用时长采集+聚合（任务计划调用；也可直接运行）
│   ├── summarize.py    # 日报/周报生成（CLI，可直接运行）
│   ├── analyze.py      # 视觉模型调用 + prompt + JSON 解析
│   ├── llm.py          # 统一 LLM 请求通道
│   └── todos.py        # 待办管理
├── data/               # 【开发版运行数据】records/reports/.env/settings.json/日志，全在这（gitignore）
├── static/             # 前端三件套 + 图标 + 字体
│   └── assets/         # icon.ico / tray.ico（spec 打包引用 icon.ico，别改名）
├── docs/               # 文档：PRD、STATUS.md、MAINTENANCE.md、skins-demo.html、images/
├── build.bat           # 唯一合法的打包入口（见第 4 节），部署到项目外的 ..\dailylog-app
└── dailylog.spec       # PyInstaller 配置（入口 app.py；datas 收 static/）

dailylog-app\              # 部署目录（项目外、仓库外）
├── dailylog.exe + _internal/   # 纯产物，构建可整目录重建
└── data\                  # 打包版运行数据：records/reports/.env/settings.json/日志
```

**三个物理位置各司其职**：源码仓库（可随意重建）、部署目录的产物部分（exe/_internal，
可被构建重建）、运行数据 `data\`（不可再生，构建镜像时被显式排除）。

## 2. 新文件该放哪

| 你要加的东西 | 放哪 | 备注 |
|---|---|---|
| 后端业务逻辑 | `core/新模块.py` | 包内互相导入一律 `from core import X` 绝对导入 |
| 前端要调的新能力 | `ui_api.py` 加方法 | 返回值必须是 JSON 友好的 dict/list |
| 前端页面/样式/脚本 | `static/` | 改完必须重跑 build.bat 才对打包版生效 |
| 可调参数 | `core/config.py` | 不要在别的模块里散落魔法数字 |
| 文档 | `docs/` | 截图类素材进 `docs/images/` |
| 图标/字体等静态资源 | `static/assets/`、`static/fonts/` | 改图标注意同步 spec 里的 icon 路径 |

**core 模块的两种身份**：capture / usage / summarize 会被任务计划或命令行**直接运行**
（如 `pythonw core\capture.py`），所以它们文件头部有 sys.path 引导代码——别删；
其余模块（config/llm/analyze/todos）只会被 import，不需要引导。

**新增 core 模块后**：无需改 dailylog.spec，PyInstaller 会从 `app.py` 静态分析跟进；
但若模块是**运行时动态 import** 的，要加进 spec 的 `hiddenimports`。

## 3. 数据目录：由 DATA_DIR 决定（最容易踩的坑）

数据目录统一由 `core/config.py` 的 `DATA_DIR` 决定：**永远是 BASE_DIR 下的 `data\` 子目录**。

- **开发版**（`python app.py`）：`项目根\data\`
- **打包版**（`dailylog-app\dailylog.exe`）：frozen 模式，BASE_DIR = exe 所在目录，
  即 `dailylog-app\data\`

两套目录内容相同：records/、reports/、screenshots/、.env（密钥）、settings.json、
state.json、.last_cleanup、dailylog.log。

排查任何"数据不见了/设置没生效"的问题，第一步先确认看的是哪一套。
桌面快捷方式指向的是打包版。

## 4. 打包

**只允许用 `build.bat`，禁止手敲 PyInstaller 命令直接输出到部署目录。**

历史教训：PyInstaller onedir 会**清空重建输出目录**，2026-08-04 曾因直接往含数据的
目录打包丢失过不可恢复的记录。现在的防御是双重的：

1. 打包先输出到临时 `dist_build\` → robocopy `/MIR /XD data` 镜像到项目外的 `..\dailylog-app` → 删临时目录
2. 运行数据统一在 `data\` 子目录（DATA_DIR），镜像时被显式排除——即使误删部署目录的产物部分也不伤数据；
   **新增任何"写在程序目录下的数据文件"都必须放进 data\（走 config.DATA_DIR），不要散在 exe 旁**

**维护规则**：
- 改动部署流程前先想清楚"这次操作会让哪些文件变化"，不确定就先备份
- 打包后验证三件事：exe 能启动、日志正常、`dailylog-app\data\records` 当日文件还在
- 桌面快捷方式与任务计划（DailyLogCapture/DailyLogUsage）指向部署目录的 exe；
  换部署位置时三处要同步更新

## 5. 状态文档约定

**只维护一个 `docs/STATUS.md`**：

- 每次会话结束更新它：「架构要点」只保留仍然成立的决策，「遗留 / 注意事项」删掉已解决的，
  本次改动压缩几行追加进「变更日志」
- 不再新建 `STATUS-日期.md` 之类的流水文件；历史过程查 git log
- 过时的方案用删除线标记后，若被新方案完全取代就直接删掉

## 6. 其他约定

- **吞异常 = 欠债**：所有 except 至少 logger.error 或注明为何可忽略；GUI/定时程序第一行就建日志
  （已有统一日志：dailylog.log，RotatingFileHandler）
- 破坏性操作（清缓存、重建目录、批量删除）动手前先列出"哪些文件会变"，有不可再生内容先备份

## 7. Git 提交规范

### 格式

```
<type>:<中文描述>
```

- **冒号后不加空格**（与现有 git log 保持一致）
- 描述用中文，一句话说清"改了什么、为什么"；避免只写文件名或"更新""修改"这类空词
- 一行以内；更多背景写进正文（空一行后）或 `docs/STATUS.md` 的变更日志

### type 取值

| type | 用途 | 示例（来自本仓库真实历史） |
|------|------|------|
| `feat` | 新功能、新能力 | `feat:截屏分析接入前台窗口元数据（进程名+窗口标题），提升分类与应用识别消歧` |
| `fix` | 修 bug | `fix:修复专注时长显示浮点尾数与皮肤回退问题` |
| `perf` | 性能优化（不改行为） | `perf:零窗口托盘化降低常驻内存` |
| `refactor` | 重构（不改功能） | `refactor:业务模块分层进 core/，清理冗余文件与过时文档，新增 MAINTENANCE 维护指南` |
| `docs` | 纯文档改动 | `docs:状态待办销项（结构整理与图标已提交）` |
| `chore` | 构建/工具/杂务 | `chore:build.bat 排除清单补充 .last_cleanup` |

### 拆分原则

- **一个 commit 只做一件事**：不相关的改动拆开提交（如"结构重构"和"换图标"分两个 commit）
- 功能代码与它对应的 STATUS.md 更新可放同一 commit；纯文档改动单独用 `docs:`
- 提交前 `git status` + `git diff` 核对暂存内容，只提交本次改动相关文件；
  运行数据（records/reports/日志/密钥）永远不入库（.gitignore 已覆盖，勿绕过）
