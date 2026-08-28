# AGENTS.md

## What This Is

Windows desktop app (Python 3.10+) that auto-captures screenshots every 10 min, analyzes them with a vision model (NVIDIA NIM), and generates daily/weekly reports via DeepSeek. No resident process — Windows Task Scheduler drives capture.

## Commands

| Action | Command |
|--------|---------|
| Run app (dev) | `python app.py` |
| Capture only (headless) | `pythonw core\capture.py` |
| Today's daily report | `python core\summarize.py` |
| Specific day report | `python core\summarize.py --day 2026-07-31` |
| Weekly report | `python core\summarize.py --week 2026-07-31` |
| Package (safe) | `build.bat` |
| Package (direct — AVOID) | `pyinstaller dailylog.spec` (wipes output dir!) |
| Usage self-check | `python core\usage.py --selfcheck` |

## Architecture

```
app.py          → Desktop entry: pywebview frameless window + pystray tray
ui_api.py       → Pure Python API bridge (no GUI deps, testable headlessly)
core/
  config.py     → All tunable params, paths, .env loading, logging setup
  capture.py    → Screenshot pipeline: idle check → mss → dedup → analyze → write → delete
  analyze.py    → NVIDIA NIM vision model call + lenient JSON parse
  llm.py        → Unified OpenAI-compatible chat completions (shared requests.Session)
  summarize.py  → DeepSeek daily/weekly report generation
  usage.py      → Foreground window sampling + aggregation
  todos.py      → Todo management with tombstone-based AI dedup
```

## Packaging Gotcha

**NEVER run `pyinstaller dailylog.spec` directly.** It wipes the output directory. Always use `build.bat`, which builds to a temp dir then robocopies to `../dailylog-app` (excluding `data/`).

## Data Layout

- All runtime data: `data/` subdir (`.env`, `settings.json`, `records/`, `reports/`, `dailylog.log`)
- `.env` holds API keys — never commit or distribute
- WebView2 data pinned to `%LOCALAPPDATA%\dailylog\webview`
- Packaged build data lives in `dailylog-app\data\` (same structure)

## API Keys

Two keys required in `data/.env` (see `.env.example`):
- `ANALYZE_API_KEY` — NVIDIA NIM (vision model, default `minimaxai/minimax-m3`)
- `DEEPSEEK_API_KEY` — DeepSeek (report generation)

## Task Scheduler

App auto-registers two scheduled tasks on startup:
- `DailyLogCapture` — screenshot cycle (configurable interval, default 10 min)
- `DailyLogUsage` — foreground app sampling (every 2 min)

Task enable/disable uses COM (fast) with schtasks fallback (slow). See `ui_api.py`.

## Imports Convention

All `core/` modules use absolute imports: `from core import config`. The `capture.py` and `usage.py` are standalone entry points (have `sys.path.insert` for direct execution).

## Key Quirks

- pywebview 6 zero-window loop: closing the window makes `start()` return; tray "Open" calls `start()` again (undocumented but confirmed via source)
- `private_mode=False` required for localStorage persistence across sessions
- COM must be initialized per-thread (`pythoncom.CoInitialize`) — MTA from pywebview bridge threads is tolerated
- ctypes win32 handle calls require explicit `argtypes`/`restype` for 64-bit handles (classic truncation bug)
- Screenshot hides app window before capture, restores after — foreground metadata sampled before hide
- API failures write retry markers; dedup allows retry even if frame unchanged
- `requests.Session` uses `trust_env=False` to bypass system proxy

## Verification

No formal test suite. Verify with:
1. `python core\usage.py --selfcheck` — validates usage aggregation logic
2. Launch app, check Settings page loads, try manual capture
3. Check `data\dailylog.log` for runtime errors
