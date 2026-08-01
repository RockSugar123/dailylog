"""dailylog 入口：截屏 → 过滤 → 去重 → 分析 → 写入时间线 → 删截图。

由 Windows 任务计划程序每 10 分钟调用一次（pythonw 运行，无控制台）。
"""
import ctypes
import hashlib
import json
import sys
import time
from datetime import datetime

import mss
import mss.tools

import analyze
import config

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

_logger = config.setup_logging()


def log(msg: str) -> None:
    print(f"[dailylog] {datetime.now():%H:%M:%S} {msg}", flush=True)
    _logger.info(msg)


def last_input_idle_seconds() -> float:
    """距上次键盘/鼠标输入的秒数（GetLastInputInfo）。"""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def is_black_screen(raw: bytes) -> bool:
    """每 400 像素采样 1 个，>99% 亮度接近 0 判定为黑屏/睡眠。"""
    dark = total = 0
    for i in range(0, len(raw), 400 * 4):
        b, g, r = raw[i], raw[i + 1], raw[i + 2]
        total += 1
        if b + g + r < 30:
            dark += 1
    return total > 0 and dark / total > 0.99


def load_state() -> dict:
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    config.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def append_record(ts: datetime, record: dict) -> None:
    """追加一条记录到当日时间线 md 与 raw jsonl。"""
    config.RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)

    md_path = config.RECORDS_DIR / f"{ts:%Y-%m-%d}.md"
    if not md_path.exists():
        md_path.write_text(f"# {ts:%Y-%m-%d} 工作日志\n\n", encoding="utf-8")

    label = config.ACTIVITY_LABELS.get(record.get("activity", ""), "其他")
    lines = [f"## {ts:%H:%M} · {label}", str(record.get("summary") or "")]
    if record.get("detail"):
        lines.append(str(record["detail"]))
    notes = []
    if record.get("progress"):
        notes.append(f"进展：{record['progress']}")
    if record.get("todo"):
        notes.append(f"待办：{record['todo']}")
    if notes:
        lines.append(" | ".join(notes))
    with md_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")

    with (config.RAW_DIR / f"{ts:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts.isoformat(timespec="seconds"), **record}, ensure_ascii=False) + "\n")


def main() -> int:
    if not config.DASHSCOPE_API_KEY:
        log("未配置 DASHSCOPE_API_KEY，请在 .env 中填写后重试")
        return 1

    if config.IDLE_ENABLED and last_input_idle_seconds() > config.IDLE_MINUTES * 60:
        log(f"鼠标空闲超过 {config.IDLE_MINUTES} 分钟，跳过本次")
        return 0

    config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    png_path = None
    try:
        with mss.MSS() as sct:
            monitor = sct.monitors[config.MONITOR_INDEX]
            raw = sct.grab(monitor)

            if is_black_screen(raw.raw):
                log("屏幕为黑屏/睡眠，跳过本次")
                return 0

            digest = hashlib.md5(raw.raw).hexdigest()
            state = load_state()
            # 上次分析失败（last_failed）时放行：即使画面未变也重试，避免去重把重试挡掉
            if digest == state.get("last_hash") and not state.get("last_failed"):
                log("画面无变化，跳过本次")
                return 0

            png_path = config.SCREENSHOTS_DIR / f"{ts:%Y%m%d_%H%M%S}.png"
            mss.tools.to_png(raw.rgb, raw.size, output=str(png_path))
    except Exception as e:
        log(f"截屏失败: {e}")
        if png_path and png_path.exists():
            png_path.unlink(missing_ok=True)
        return 1

    record = None
    try:
        for attempt in range(config.MAX_RETRIES + 1):
            try:
                record = analyze.call_analyze(analyze.encode_image(png_path))
                break
            except Exception as e:
                log(f"分析失败(第{attempt + 1}次): {e}")
                if attempt < config.MAX_RETRIES:
                    time.sleep(3)
    finally:
        png_path.unlink(missing_ok=True)  # 即用即删，磁盘不保留原始画面

    if record is None:
        # 占位条目 + last_failed 标记：下个 tick 即使画面未变也重试（去重检查放行失败标记）。
        # 若当天最后一条已是失败占位，不再重复追加（避免连续故障时垃圾堆积）。
        raw_path = config.RAW_DIR / f"{ts:%Y-%m-%d}.jsonl"
        last_line = ""
        if raw_path.exists():
            try:
                lines = raw_path.read_text(encoding="utf-8").splitlines()
                last_line = lines[-1] if lines else ""
            except OSError:
                pass
        if "分析失败" not in last_line:
            record = {
                "activity": "other",
                "summary": "分析失败，下轮自动重试",
                "detail": "", "progress": "", "todo": "", "apps": [], "contains_sensitive": False,
            }
            append_record(ts, record)
        save_state({"last_hash": digest, "last_failed": True})
        return 1

    save_state({"last_hash": digest})  # 成功：整体覆盖 state.json，同时清除 last_failed 标记
    append_record(ts, record)
    log(f"已记录: {record['activity']} | {record['summary'][:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
