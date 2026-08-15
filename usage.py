"""dailylog 应用使用时长统计：采集 + 聚合。

- 采集：由任务计划 DailyLogUsage 每 2 分钟驱动一次（pythonw 运行，无控制台），
  读取前台窗口的进程名，追加到 records/usage/YYYY-MM-DD.jsonl，进程即退，不常驻。
- 聚合：ui_api 调 aggregate() 按日/周/月汇总各应用时长（采样次数 × 间隔，估算）。
- 隐私：只记进程名（小写含 .exe），不记窗口标题——标题可能含文档名/网页标题。
"""
import ctypes
import json
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import config

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

_logger = config.setup_logging()


def foreground_app() -> str | None:
    """当前前台窗口的进程名（小写，含 .exe 后缀）；读取失败返回 None。"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    # 64 位句柄/指针：不声明 argtypes 时 ctypes 默认按 c_int 截断（经典坑，见 capture.py）
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return Path(buf.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)


def append_usage(ts: datetime, app: str) -> None:
    """追加一条采样记录到当日 usage jsonl。"""
    config.USAGE_DIR.mkdir(parents=True, exist_ok=True)
    with (config.USAGE_DIR / f"{ts:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts.isoformat(timespec="seconds"), "app": app}, ensure_ascii=False) + "\n")


def aggregate(start: date, end: date, granularity: str = "day") -> dict:
    """统计 [start, end]（含首尾）区间内各应用时长。

    时长 = 采样次数 × 间隔分钟（估算）。返回 {"total_min": int, "apps": [...], "buckets": [...]}：
    - apps：各应用时长 [{app, minutes, pct, sessions, avg, streak, first, last}]，按时长降序：
      sessions 会话次数（相邻采样间隔 > 1.5 倍间隔视为新会话）、avg 平均会话时长（分钟）、
      streak 最长连续使用（分钟）、first/last 首次/最后使用时间（ISO）
    - buckets：时段分布 [{label, minutes}]，按时间升序；granularity="hour" 按小时
      （label 为 "HH:00"，日视图用），否则按天（label 为 "YYYY-MM-DD"）
    无数据时 apps/buckets 均为空列表。
    """
    interval = config.USAGE_INTERVAL_MINUTES
    counts: dict[str, int] = {}
    buckets: dict[str, int] = {}
    samples: dict[str, list[str]] = {}  # app → 采样时间列表（用于会话切分）
    d = start
    while d <= end:
        path = config.USAGE_DIR / f"{d:%Y-%m-%d}.jsonl"
        if path.exists():
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    app = rec.get("app")
                    if not app:
                        continue
                    counts[app] = counts.get(app, 0) + 1
                    ts = rec.get("ts", "")
                    if ts:
                        samples.setdefault(app, []).append(ts)
                    key = ts[11:13] if granularity == "hour" else ts[:10]
                    if key:
                        buckets[key] = buckets.get(key, 0) + 1
            except (OSError, json.JSONDecodeError) as e:
                _logger.warning("usage 数据读取失败 %s: %s", path.name, e)
        d += timedelta(days=1)
    if not counts:
        return {"total_min": 0, "apps": [], "buckets": []}
    total_min = sum(counts.values()) * interval
    gap_limit = interval * 90  # 秒：超过 1.5 倍采样间隔视为新会话
    apps = []
    for app, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        tss = sorted(samples.get(app, []))
        sessions = streak_n = max_streak_n = 0
        first, last, prev = "", "", None
        for ts in tss:
            if not first:
                first = ts
            last = ts
            if prev is None or (datetime.fromisoformat(ts) - datetime.fromisoformat(prev)).total_seconds() > gap_limit:
                sessions += 1
                streak_n = 1
            else:
                streak_n += 1
            max_streak_n = max(max_streak_n, streak_n)
            prev = ts
        minutes = n * interval
        apps.append({
            "app": app,
            "minutes": minutes,
            "pct": round(minutes / total_min * 100, 1),
            "sessions": sessions,
            "avg": round(minutes / sessions) if sessions else 0,
            "streak": max_streak_n * interval,
            "first": first,
            "last": last,
        })
    if granularity == "hour":
        bucket_list = [{"label": f"{k}:00", "minutes": n * interval} for k, n in sorted(buckets.items())]
    else:
        bucket_list = [{"label": k, "minutes": n * interval} for k, n in sorted(buckets.items())]
    return {"total_min": total_min, "apps": apps, "buckets": bucket_list}


def main() -> int:
    """一次采样：空闲跳过 → 读前台应用 → 追加记录。任务计划每 2 分钟调用。"""
    if not config.USAGE_ENABLED:
        return 0
    if config.IDLE_ENABLED:
        from capture import last_input_idle_seconds  # 延迟导入避免循环依赖（capture 不依赖 usage）
        if last_input_idle_seconds() > config.IDLE_MINUTES * 60:
            return 0
    app = foreground_app()
    if not app:
        _logger.warning("读取前台应用失败，跳过本次采样")
        return 1
    append_usage(datetime.now(), app)
    return 0


def _demo() -> None:
    """自检：造临时数据验证聚合口径（采样数 × 间隔，占比归一）。"""
    tmp = Path(tempfile.mkdtemp(prefix="usage_selfcheck_"))
    old = config.USAGE_DIR
    config.USAGE_DIR = tmp
    try:
        (tmp / "2026-08-05.jsonl").write_text(
            '{"ts": "2026-08-05T09:00:00", "app": "code.exe"}\n'
            '{"ts": "2026-08-05T09:02:00", "app": "code.exe"}\n'
            '{"ts": "2026-08-05T09:04:00", "app": "chrome.exe"}\n', encoding="utf-8")
        r = aggregate(date(2026, 8, 5), date(2026, 8, 5))
        assert r["total_min"] == 6, r
        # code.exe 两跳连续（1 会话、最长 4 分钟）；chrome.exe 一跳（1 会话、2 分钟）
        assert r["apps"][0]["app"] == "code.exe" and r["apps"][0]["minutes"] == 4 and r["apps"][0]["pct"] == 66.7, r
        assert r["apps"][0]["sessions"] == 1 and r["apps"][0]["streak"] == 4 and r["apps"][0]["avg"] == 4, r
        assert r["apps"][0]["first"] == "2026-08-05T09:00:00" and r["apps"][0]["last"] == "2026-08-05T09:02:00", r
        assert r["apps"][1] == {"app": "chrome.exe", "minutes": 2, "pct": 33.3,
                                "sessions": 1, "avg": 2, "streak": 2,
                                "first": "2026-08-05T09:04:00", "last": "2026-08-05T09:04:00"}, r
        # 时段分布：小时粒度按 ts 的小时归桶（三条 09 点采样合并），按时间升序
        rh = aggregate(date(2026, 8, 5), date(2026, 8, 5), granularity="hour")
        assert rh["buckets"] == [{"label": "09:00", "minutes": 6}], rh
        # 区间跨天：8-04 无数据文件，不影响
        r2 = aggregate(date(2026, 8, 4), date(2026, 8, 5))
        assert r2["total_min"] == 6, r2
        print("usage 聚合自检通过:", r, "| buckets:", rh["buckets"])
    finally:
        config.USAGE_DIR = old
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _demo()
        sys.exit(0)
    sys.exit(main())
