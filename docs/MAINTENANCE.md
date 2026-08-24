# dailylog 维护指南

> 写给下一个开发者。读完这页，你就知道每类文件该放哪、哪些目录碰不得、打包怎么跑。
> 项目当前状态与架构决策见 [STATUS.md](STATUS.md)，本页只讲"怎么维护"。

## 1. 目录结构总览

```
dailylog/
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
├── static/             # 前端三件套 + 图标 + 字体
│   └── assets/         # icon.ico / tray.ico（spec 打包引用 icon.ico，别改名）
├── docs/               # 文档：PRD、STATUS.md、MAINTENANCE.md、skins-demo.html、images/
├── records/            # 【运行时产物】时间线记录 + raw jsonl + usage 采样（gitignore）
├── reports/            # 【运行时产物】生成的日报/周报（gitignore）
├── build.bat           # 唯一合法的打包入口（见第 4 节）
├── dailylog.spec       # PyInstaller 配置（入口 app.py；datas 收 static/）
└── dist/dailylog/      # 部署目录 = 打包版的运行环境（含数据，见第 3 节）
```

**根目录的杂项文件都是开发版运行数据**：`.env`（密钥）、`settings.json`、`state.json`、
`dailylog.log`、`.last_cleanup`。它们由程序生成、已被 gitignore，**不要手动创建或提交**。

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

## 3. 两套数据目录（最容易踩的坑）

同一个程序有两种跑法，**数据目录不同**（由 `core/config.py` 的 BASE_DIR 决定）：

- **开发版**（`python app.py`）：数据在项目根目录（records/reports/settings.json 都在这）
- **打包版**（`dist\dailylog\dailylog.exe`）：frozen 模式，BASE_DIR = exe 所在目录，
  数据全在 `dist\dailylog\` 里

排查任何"数据不见了/设置没生效"的问题，第一步先确认看的是哪一套目录。
桌面快捷方式指向的是打包版。

## 4. 打包（红线，出过事故）

**只允许用 `build.bat`，禁止手敲 PyInstaller 命令直接输出到 `dist\dailylog\`。**

原因：PyInstaller onedir 会**清空重建输出目录**，而 `dist\dailylog\` 里混着运行数据
（.env 密钥、全部工作记录）。2026-08-04 曾因此丢失过不可恢复的记录。

build.bat 的流程：PyInstaller 先输出到临时 `dist_build\` → robocopy `/MIR` 镜像部署到
`dist\dailylog\`，用 `/XF /XD` 排除清单保住数据文件 → 删临时目录。

**维护规则**：
- 程序新增"写在 exe 同目录的数据文件"时，必须同步把文件名加进 build.bat 的 `/XF` 排除清单
  （现有排除：.env .last_cleanup settings.json state.json dailylog.log；/XD：records reports screenshots）
- 改动部署流程前先想清楚"这次操作会让 dist 下哪些文件变化"，不确定就先备份
- 打包后验证三件事：exe 能启动、日志正常、records 当日文件还在

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
- 提交信息风格参考 git log：`feat:` / `perf:` / `docs:` / `fix:` 前缀 + 中文描述
