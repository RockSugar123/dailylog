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
- **Smart skipping**: pauses when mouse/keyboard are idle (≥5 min by default), skips black screens/sleep, deduplicates identical frames (md5 comparison)
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
| LLM calls | requests → NVIDIA NIM (vision model analyzes screenshots) + DeepSeek (generates daily/weekly reports) |
| Scheduling | Windows Task Scheduler (schtasks) |
| Configuration | python-dotenv (`.env`) + settings.json |
| Packaging | PyInstaller (onedir mode) |

## 🚀 Quick Start

### Requirements

- Windows 10/11 (Task Scheduler + mss capture + GetLastInputInfo are all Windows capabilities)
- Python 3.10+ (dev-verified on 3.13)
- Two API keys:
  - **NVIDIA NIM** (screenshot analysis, vision model, default `minimaxai/minimax-m3`): <https://build.nvidia.com>
  - **DeepSeek** (daily/weekly report generation): <https://platform.deepseek.com>

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

Fill in the keys following [.env.example](.env.example) (place it in the source directory during development, or next to the exe for the packaged build — the packaged build only reads the .env next to the exe):

```
ANALYZE_API_KEY=your-NVIDIA-key
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
| Capture only (headless, called by Task Scheduler) | `pythonw capture.py` |
| Generate today's daily report | `python summarize.py` |
| Generate a specific day's report | `python summarize.py --day 2026-07-31` |
| Generate a weekly report (ISO week of that date) | `python summarize.py --week 2026-07-31` |
| Packaged desktop app | `dist\dailylog\dailylog.exe` |
| Packaged capture | `dist\dailylog\dailylog.exe --capture` |
| Packaged diagnostics (prints scheduler/config status) | `dist\dailylog\dailylog.exe --diag` |

### Registering the Windows scheduled task (optional; auto-registered on app startup)

```bash
# Development (pythonw = no console window; /f overwrites an existing task)
schtasks /create /tn DailyLogCapture /tr "\"<full-path-to-pythonw>\" <absolute-project-path>\capture.py" /sc minute /mo 10 /f

# Packaged build (onedir, exe under dist\dailylog\)
schtasks /create /tn DailyLogCapture /tr "\"C:\path\to\dist\dailylog\dailylog.exe\" --capture" /sc minute /mo 10 /f

schtasks /run /tn DailyLogCapture    # Trigger once manually (smoke test)
schtasks /delete /tn DailyLogCapture /f   # Uninstall
```

## ⚙️ How It Works

```
┌──────────────────── Scheduled task DailyLogCapture (every 10 minutes) ────────────────────┐
│  capture.py: idle check → mss screenshot → black-frame check → dedupe                    │
│              → vision model analysis → write timeline → delete screenshot                │
└──────────────────────────────────────────────────────────────────────────────────────────┘
        │ writes
        ▼
  records/YYYY-MM-DD.md (human-readable timeline) + records/raw/YYYY-MM-DD.jsonl (structured raw log)
        │
        ▼ manual trigger (UI button / CLI)
  summarize.py: aggregate logs → DeepSeek → reports/日报-YYYY-MM-DD.md / 周报-YYYY-Www.md
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

- `activity` categories: `coding` / `writing` / `meeting` / `research` / `communication` / `data` / `support` / `browsing` / `idle` / `other` (labels editable in [config.py](config.py))
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

8h of work ≈ 48 samples, 15–25 valid entries after dedup. Cost depends strongly on the chosen model: the default `minimaxai/minimax-m3` (NVIDIA NIM, free tier for personal accounts) — measure against your chosen model's input/output pricing.

## 📦 Project Layout

<details>
<summary>Show</summary>

```
dailylog/
├── .env                    # Two API keys (fill in yourself; never distribute)
├── requirements.txt        # mss / requests / python-dotenv / pywebview / pywin32 / pystray / pillow / pynput
├── config.py               # All tunable parameters (API, intervals, dirs, category labels)
├── capture.py              # Capture entry point (called by Task Scheduler)
├── analyze.py              # Vision model call (config.ANALYZE_MODEL swappable) + lenient JSON parsing + prompt
├── summarize.py            # DeepSeek daily/weekly report generation (CLI: --day / --week)
├── ui_api.py               # Desktop API bridge: timeline/reports/settings/scheduler (pure Python, testable without GUI)
├── app.py                  # Desktop entry: pywebview borderless window + pystray tray
├── dailylog.spec           # PyInstaller packaging config (onedir)
├── settings.json           # Runtime settings (dev build; editable in UI)
├── state.json              # Runtime state (dev build; last screenshot hash for dedup)
├── .last_cleanup           # Cleanup throttle marker (date string; skips if already cleaned today)
├── records/                # Dev-build timeline logs (raw/YYYY-MM-DD.jsonl + YYYY-MM-DD.md)
├── reports/                # Dev-build daily/weekly reports
├── static/                 # Frontend (index.html / style.css / script.js)
├── docs/                   # Docs & screenshots (images/)
└── dist/
    └── dailylog/           # Packaged build (onedir): exe + _internal/ libs
        ├── dailylog.exe    # Packaged executable (data lives next to the exe)
        ├── _internal/      # Bundled dependencies (do not touch)
        ├── .env            # Packaged-build API keys (never distribute)
        ├── settings.json   # Packaged-build runtime settings (editable in UI)
        ├── state.json      # Packaged-build runtime state
        ├── .last_cleanup   # Cleanup throttle marker
        ├── records/        # Packaged-build timeline logs (final artifacts)
        ├── reports/        # Packaged-build daily/weekly reports
        └── dailylog.log    # Packaged-build runtime log
```

> **Data locations**: packaged and dev builds are independent — packaged data lives in `dist/dailylog/` (next to the exe), dev-build data in the project root.

</details>

## 🧑‍💻 Development & Packaging

```bash
build.bat                 # Recommended: safe packaging (builds to a temp dir, then deploys — never touches runtime data)
pyinstaller dailylog.spec # Warning: onedir mode wipes and rebuilds the output directory!
```

**Important**: PyInstaller onedir packaging **wipes and rebuilds the output directory**. Without an explicit distpath, `dailylog.spec` outputs to `dist/dailylog/` — packaging directly will delete runtime data inside (`.env`, `records/`, etc.). **Always use `build.bat`** (builds to a temp `dist_build/` then deploys with a `/MIR` mirror, explicitly excluding data files/dirs).

Other notes:

- onedir mode: desktop app / capture / diagnostics all point to `dist\dailylog\dailylog.exe`; data lives **next to the exe** (`.env`, `settings.json`, `records/`, `reports/`) — never distribute `dist\dailylog\.env` containing keys
- The packaging environment needs pyinstaller installed separately
- The WebView2 data directory is pinned to `%LOCALAPPDATA%\dailylog\webview` (avoids creating a new temp dir on every launch); stale leftovers are cleaned automatically on startup

## 🩺 Troubleshooting

- **All runtime logs**: `dailylog.log` (1MB rotation, 3 copies kept), in the same directory as the source/exe
- **Scheduled task not firing**: the Settings page "Current status" shows "disabled"; check with `schtasks /query /tn DailyLogCapture`
- **API errors**: errors are logged with the first 300 chars of the response body for diagnosis (e.g. 400 = wrong model name/key)
- **Sub-minute test recording**: after writing `test_interval_seconds` (Settings page or `apply_test_interval`), the app enters a test loop in-process (Task Scheduler schema has a 1-minute minimum, so sub-minute intervals must be driven by the app process)
- **Failed-analysis placeholder**: failures write an "analysis failed, auto-retry next cycle" placeholder marked for retry — the next cycle retries even if the frame is unchanged (prevents placeholder pile-up during consecutive failures)

## ⚠️ Known Limitations

- 10-minute granularity: idle recovery can lag by up to one cycle (no daemon process)
- Duration stats (focus time, category distribution) are **estimated** from record intervals, not measured precisely
- Raw screenshots are uploaded to the cloud: the prompt guards against "output" leakage only, not "input"

## 📄 License

[MIT](LICENSE)

---

[简体中文](README.md) | **English**
