# dailylog · Today's Trail

[简体中文](README.md) | **English**

<div align="center">

![dailylog](docs/images/overview.png)

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)
![Stars](https://img.shields.io/github/stars/RockSugar123/dailylog?style=social)

**Automatically record your daily work timeline and generate daily/weekly reports in one click.**

A screenshot is taken every 10 minutes; a vision model turns each frame into a structured work log entry, and DeepSeek then turns the log into deliverable daily/weekly reports.

[Features](#-features) · [Screenshots](#-screenshots) · [Tech Stack](#-tech-stack) · [Quick Start](#-quick-start) · [Privacy](#-privacy-design)

</div>

## 📖 A Note from the Author

I built this tool casually in my spare time to test the latest DeepSeek v4 model. It's a small toy, but more than enough for everyday work logging and daily/weekly report summaries. You can configure any models you like — ask an AI to help if you're unsure. Just pick something cheap and good; you don't have to use the same two providers I did (I chose them mainly because they're free/cheap).

One more thing: whenever you download any project, **always review the code for security**. Never expose your API keys.

## ✨ Features

- **Automatic recording**: Windows Task Scheduler drives a screenshot-and-analyze cycle every 10 minutes — no resident process needed
- **Smart skipping**: pauses when mouse/keyboard are idle (≥5 min by default), skips black screens/sleep, deduplicates near-identical frames (perceptual hash — taskbar clock ticks and cursor jitter don't trigger re-analysis)
- **Manual capture**: a button on the Settings page takes a screenshot after a 5-second countdown; the app hides its own window during capture so it never appears in screenshots
- **Timeline browsing**: view activity trails by day/week/month, category time distribution, and focus-time estimates
- **App usage stats**: foreground process sampling, aggregated per app by day/week/month
- **Todo management**: todos extracted from work records, with priority and completion tracking
- **One-click reports**: generates daily reports (outcome-oriented template) and weekly reports (grouped by project) as ready-to-use Markdown
- **Privacy-first design**: screenshots are deleted immediately after analysis, output is force-redacted (see [Privacy Design](#-privacy-design))
- **Tray resident**: closing the window minimizes to the tray while recording continues; packaged as a single exe for fully automatic operation

## 🖼 Screenshots

| Overview | Timeline |
|----------|----------|
| ![Overview](docs/images/overview.png) | ![Timeline](docs/images/timeline.png) |

| App Usage | Todos |
|-----------|-------|
| ![App Usage](docs/images/app-usage.png) | ![Todos](docs/images/todos.png) |

| Settings |
|----------|
| ![Settings](docs/images/settings.png) |

## 🛠 Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ |
| Desktop GUI | [pywebview](https://pywebview.flowrl.com/) (borderless WebView2 window) + vanilla HTML/CSS/JS frontend |
| System tray | pystray + pywin32 |
| Screen capture | mss + Pillow |
| Idle detection | pywin32 (GetLastInputInfo) + pynput |
| LLM calls | requests → DashScope (vision model analyzes screenshots) + DeepSeek (generates daily/weekly reports) |
| Scheduling | Windows Task Scheduler (schtasks) |
| Configuration | python-dotenv (`.env`) + settings.json |
| Packaging | PyInstaller (onedir mode) |

## 🚀 Quick Start

### Requirements

- Windows 10/11 (Task Scheduler + mss capture + GetLastInputInfo are all Windows capabilities)
- Python 3.10+ (dev-verified on 3.13)
- Two API keys (paste them in the app's Settings page on first use, see below):
  - **Alibaba Cloud DashScope** (screenshot analysis, vision model): <https://platform.aliyuncs.com>
  - **DeepSeek** (daily/weekly report generation): <https://platform.deepseek.com>

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys (recommended: paste in the Settings page)

Open the app → **Settings → Model Service**, paste both keys → **Save** → click **Test Connection**. Saved keys take effect immediately (scheduled tasks included), no restart needed.

Alternatively, edit `.env` manually following [.env.example](.env.example) (place it in the project's `data\` directory during development; the packaged build reads `dailylog-app\data\.env` next to the deployed exe):

```
ANALYZE_API_KEY=your-DashScope-key
DEEPSEEK_API_KEY=sk-your-DeepSeek-key
```

### 3. Launch

```bash
python app.py
```

On startup the app automatically registers the Windows scheduled task `DailyLogCapture` (screenshot + analysis every 10 minutes, toggleable in the UI). Closing the window minimizes to the tray while recording continues.

### CLI usage

| Purpose | Command |
|---------|---------|
| Desktop app (recommended) | `python app.py` |
| Capture only (headless, called by Task Scheduler) | `pythonw core\capture.py` |
| Generate today's daily report | `python core\summarize.py` |
| Generate a specific day's report | `python core\summarize.py --day 2026-07-31` |
| Generate a weekly report (ISO week of that date) | `python core\summarize.py --week 2026-07-31` |
| Packaged desktop app | `..\dailylog-app\dailylog.exe` |
| Packaged capture | `..\dailylog-app\dailylog.exe --capture` |
| Packaged diagnostics (prints scheduler/config status) | `..\dailylog-app\dailylog.exe --diag` |

### Registering the Windows scheduled task (optional; auto-registered on app startup)

```bash
# Development (pythonw = no console window; /f overwrites an existing task)
schtasks /create /tn DailyLogCapture /tr "\"<full-path-to-pythonw>\" <absolute-project-path>\capture.py" /sc minute /mo 10 /f

# Packaged build (deployed outside the repo, ..\dailylog-app\)
schtasks /create /tn DailyLogCapture /tr "\"C:\path\to\dailylog-app\dailylog.exe\" --capture" /sc minute /mo 10 /f

schtasks /run /tn DailyLogCapture    # Trigger once manually (smoke test)
schtasks /delete /tn DailyLogCapture /f   # Uninstall
```

## ⚙️ How It Works

```
┌──────────────────── Scheduled task DailyLogCapture (every 10 minutes) ────────────────────┐
│  core/capture.py: idle check → mss screenshot → black-frame check → dedupe               │
│              → vision model analysis → write timeline → delete screenshot                │
└──────────────────────────────────────────────────────────────────────────────────────────┘
        │ writes
        ▼
  records/YYYY-MM-DD.md (human-readable timeline) + records/raw/YYYY-MM-DD.jsonl (structured raw log)
        │
        ▼ manual trigger (UI button / CLI)
  core/summarize.py: aggregate logs → DeepSeek → reports/日报-YYYY-MM-DD.md / 周报-YYYY-Www.md
```

## 🔧 Settings

Changed via the app's Settings page, persisted to `settings.json`:

| Key | Description | Options | Default |
|-----|-------------|---------|---------|
| `interval_minutes` | Screenshot interval | 5 / 10 / 15 / 30 / 60 | 10 |
| `recording_enabled` | Master recording switch (persisted when toggled from title bar/tray, restored on startup) | true / false | true |
| `idle_enabled` | Pause capture when input is idle | true / false | true |
| `idle_minutes` | Idle threshold | 1 / 2 / 5 / 10 / 15 / 20 / 30 | 5 |
| `report_name` | "Reporter" name in daily reports; empty = line omitted | any text | "" |
| `retention_days` | Local record retention in days, auto-cleaned when expired (0 = keep forever) | 0 / 7 / 14 / 30 / 60 / 90 | 0 |
| `test_interval_seconds` | Test-only sub-minute capture interval (cleared when set back to minutes; not for production) | any seconds | none |

Cleanup rules: when `retention_days` is non-zero, the app checks on startup and on each capture (at most once per day) and deletes `records/` logs and `reports/` reports older than the window (weekly reports use Sunday as the boundary and are kept if they overlap the window); reports with unparseable filenames are never deleted. The throttle marker lives in `.last_cleanup`.

Manual capture (Settings page button) forces a record: it skips idle detection and frame dedup — ideal for meetings or demos. All captures (scheduled and manual) hide the app window before grabbing the screen and restore it immediately after saving.

## 📦 Data Artifacts

### Timeline `records/YYYY-MM-DD.md`

```markdown
# 2026-07-31 Work Log

## 09:10 · Development
Fixed a login-token-expiry handling bug in the auth module and request-interceptor logic (VS Code).
Progress: verified locally, pending commit | Todo: add unit tests for timeout retry
```

### Raw log `records/raw/YYYY-MM-DD.jsonl`

One JSON object per line:

```json
{"ts": "2026-07-31T09:10:00", "activity": "coding", "summary": "…",
 "detail": "…", "progress": "…", "todo": "…", "apps": ["VS Code"], "contains_sensitive": false}
```

- `activity` categories: `coding` / `writing` / `meeting` / `research` / `communication` / `data` / `support` / `browsing` / `idle` / `other` (labels editable in [core/config.py](core/config.py))
- `contains_sensitive`: the entry involved sensitive content (already redacted)

### Reports `reports/`

- Daily: `日报-YYYY-MM-DD.md` (outcome-oriented template: key outcomes / metrics / highlights / risks & blockers / top 3 for tomorrow)
- Weekly: `周报-YYYY-Www.md` (grouped by project/theme, with time distribution, open issues, next-week suggestions)

## 🔒 Privacy Design

1. **Use-and-delete**: screenshots exist only in memory → temp file → API analysis, then are deleted immediately; no raw frames are kept on disk
2. **Output redaction**: the analysis prompt forces the model to replace contact identities, account numbers, keys, full links, and other sensitive fields in its output, keeping only redacted work items
3. **Boundary note**: raw screenshots are uploaded to the selected model provider's servers; redaction rules constrain the "output" only, not the "input" — input-side protection requires extending local blurring yourself
4. Timeline logs are stored only in the local dailylog directory

## 💰 Cost Estimate (with dedup)

8h of work ≈ 48 samples, 15–25 valid entries after dedup. Cost depends strongly on the chosen model: the configured vision model on DashScope (see `core/config.py`) — measure against your chosen model's input/output pricing.

## 📦 Project Layout

<details>
<summary>Show</summary>

```
dailylog/
├── .env                    # Two API keys (fill in yourself; never distribute)
├── requirements.txt        # mss / requests / python-dotenv / pywebview / pywin32 / pystray / pillow / pynput
├── core/                   # Business modules (always use absolute `from core import X` internally)
│   ├── config.py           # All tunable parameters (API, intervals, dirs, category labels)
│   ├── capture.py          # Capture entry point (called by Task Scheduler; directly runnable)
│   ├── analyze.py          # Vision model call (config.ANALYZE_MODEL swappable) + lenient JSON parsing + prompt
│   ├── summarize.py        # DeepSeek daily/weekly report generation (CLI: --day / --week; directly runnable)
│   ├── usage.py            # App usage-time sampling & aggregation (directly runnable)
│   ├── todos.py            # Todo management
│   └── llm.py              # Unified LLM call channel
├── ui_api.py               # Desktop API bridge: timeline/reports/settings/scheduler (pure Python, testable without GUI)
├── app.py                  # Desktop entry: pywebview borderless window + pystray tray
├── dailylog.spec           # PyInstaller packaging config (onedir)
├── data/                   # Dev-build runtime data: records/ reports/ .env settings.json logs, etc.
├── static/                 # Frontend (index.html / style.css / script.js)
└── docs/                   # Docs & screenshots (images/)

# Deploy directory (outside the repo): ..\dailylog-app\
# └── dailylog.exe + _internal/   pure product, contains no data
# Packaged-build runtime data: ..\dailylog-app\data\ (records/reports/.env/settings.json etc., excluded from builds)
```

> **Data locations**: determined by `DATA_DIR` in `core/config.py`, always the `data\` subfolder of BASE_DIR — dev build uses the project's `data/`, packaged build uses `dailylog-app\data\`.

</details>

## 🧑‍💻 Development & Packaging

```bash
build.bat                 # The only entry: builds to a temp dir, then mirror-deploys to ..\dailylog-app (outside the repo)
pyinstaller dailylog.spec # Warning: onedir mode wipes and rebuilds the output directory!
```

**Important**: PyInstaller onedir packaging **wipes and rebuilds the output directory**. **Always use `build.bat`** (builds to a temp `dist_build/`, then mirror-deploys to `..\dailylog-app` outside the repo with `/XD data`). Runtime data lives in the deploy directory's `data\` subfolder, which the mirror excludes, so builds can never touch it.

Other notes:

- Packaged-build data (`.env`, `settings.json`, `records/`, `reports/`) lives in `dailylog-app\data\`; never distribute the key-containing `.env`
- When changing the deploy location, update three places: `DEPLOY_DIR` in build.bat, the desktop shortcut, and the exe paths of scheduled tasks DailyLogCapture / DailyLogUsage
- The packaging environment needs pyinstaller installed separately
- The WebView2 data directory is pinned to `%LOCALAPPDATA%\dailylog\webview` (avoids creating a new temp dir on every launch); stale leftovers are cleaned automatically on startup

## 🩺 Troubleshooting

- **All runtime logs**: `dailylog.log` (1MB rotation, 3 copies kept) under each build's `data\` directory (project root for dev, next to the exe for packaged)
- **Scheduled task not firing**: the Settings page "Current status" shows "disabled"; check with `schtasks /query /tn DailyLogCapture`
- **API errors**: errors are logged with the first 300 chars of the response body for diagnosis (e.g. 400 = wrong model name/key)
- **Sub-minute test recording**: after writing `test_interval_seconds` (Settings page or `apply_test_interval`), the app enters a test loop in-process (Task Scheduler schema has a 1-minute minimum, so sub-minute intervals must be driven by the app process)
- **Failed-analysis placeholder**: failures write an "analysis failed, auto-retry next cycle" placeholder marked for retry — the next cycle retries even if the frame is unchanged (prevents placeholder pile-up during consecutive failures)

## ⚠️ Known Limitations

- 10-minute granularity: idle recovery can lag by up to one cycle (no daemon process)
- Duration stats (focus time, category distribution) are **estimated** from record intervals, not measured precisely
- Raw screenshots are uploaded to the cloud: the prompt guards against "output" leakage only, not "input"

## 📄 License

MIT

---

[简体中文](README.md) | **English**
