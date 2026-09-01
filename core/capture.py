"""dailylog 入口：截屏 → 过滤 → 去重 → 分析 → 写入时间线 → 删截图。

由 Windows 任务计划程序每 10 分钟调用一次（pythonw 运行，无控制台）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base64
import ctypes
import json
import re
import time
from datetime import datetime, timedelta

import mss
import mss.tools
from PIL import Image

from core import analyze, config, usage

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


def _hide_app_windows() -> list:
    """截屏前隐藏 dailylog 应用窗口，返回 [(句柄, 是否最小化)] 供 _show_app_windows 恢复。

    窗口无法从屏幕截图中排除，只能截屏瞬间隐藏自身窗口（SW_HIDE），截图保存后立即恢复。
    只隐藏"当前可见"的窗口——用户主动最小化到托盘的窗口不会被碰；
    记录隐藏前是否最小化，恢复时保持原状态且不激活（不抢焦点、不弹回前台）。
    """
    user32 = ctypes.windll.user32
    # 64 位句柄：不声明 argtypes 时 ctypes 默认按 c_int 截断，ShowWindow 会失败（经典坑）
    user32.EnumWindows.restype = ctypes.c_bool
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.IsIconic.restype = ctypes.c_bool
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if config.APP_TITLE in buf.value and user32.IsWindowVisible(hwnd):
            found.append((hwnd, user32.IsIconic(hwnd)))  # 只隐藏可见窗口（托盘化的窗口不碰）
        return True

    user32.EnumWindows(_cb, 0)
    for hwnd, _ in found:
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
    if found:
        time.sleep(0.3)  # 等窗口真正从画面消失再截屏
    return found


def _show_app_windows(hwnds: list) -> None:
    """恢复先前由 _hide_app_windows 隐藏的窗口（只操作传入句柄，不碰托盘窗口）。

    不激活窗口（SW_SHOWNOACTIVATE=4）；隐藏前已最小化的窗口保持最小化
    （SW_SHOWMINNOACTIVE=7），避免截屏后窗口被 SW_SHOW 激活弹回前台抢焦点。
    """
    user32 = ctypes.windll.user32
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    for hwnd, was_minimized in hwnds:
        user32.ShowWindow(hwnd, 7 if was_minimized else 4)


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


def _workarea_crop_box(monitor: dict):
    """工作区（不含任务栏）在截图里的像素范围 (left, top, right, bottom)；取不到返回 None。

    SPI_GETWORKAREA 只返回主屏工作区，而主屏在 Windows 恒位于原点，因此仅在
    截的就是原点主屏时才裁剪；该 API 与 mss 用的是同一套（进程 DPI 虚拟化）
    坐标，可直接换算。任务栏时钟每分钟必变，不裁掉它签名就会一直变。
    """
    if config.MONITOR_INDEX != 1 or monitor.get("left") or monitor.get("top"):
        return None

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    user32 = ctypes.windll.user32
    user32.SystemParametersInfoW.argtypes = [
        ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = ctypes.c_bool
    rect = RECT()
    if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
        return None
    left, top = max(0, rect.left), max(0, rect.top)
    right = min(monitor["width"], rect.right)
    bottom = min(monitor["height"], rect.bottom)
    if right - left < monitor["width"] / 2 or bottom - top < monitor["height"] / 2:
        return None  # 工作区异常（不足半屏）不裁，保守处理
    return (left, top, right, bottom)


def _screen_signature(rgb: bytes, size: tuple, crop_box) -> bytes:
    """画面感知签名：裁掉任务栏后缩到 32×32 灰度图（1 字节/像素）。

    整屏原始字节的 md5 会被任务栏时钟、光标位置击穿（每次必不同）；
    降到 32×32 后这类亚像素级抖动落进比较阈值，真实内容变化则明显超阈。
    """
    img = Image.frombytes("RGB", size, rgb)
    if crop_box:
        img = img.crop(crop_box)
    return img.convert("L").resize(config.DEDUP_SIG_SIZE, Image.LANCZOS).tobytes()


def _dhash_bits(gray: bytes) -> int:
    """灰度图 dHash：每行相邻像素的梯度位（右像素更亮记 1）。"""
    w, h = config.DEDUP_SIG_SIZE
    bits = 0
    for y in range(h):
        row = gray[y * w:(y + 1) * w]
        for x in range(w - 1):
            bits = (bits << 1) | (row[x + 1] > row[x])
    return bits


def _screen_changed(prev: bytes, cur: bytes) -> bool:
    """两帧签名比较：dHash 汉明距离或灰度平均像素差超阈即视为"画面变了"。

    汉明距离抓结构变化（如角落弹出小通知，均值几乎不动但布局变了），
    像素差抓整体亮度变化；任一超阈都按变化处理。
    """
    hamming = bin(_dhash_bits(prev) ^ _dhash_bits(cur)).count("1")
    diff = sum(abs(a - b) for a, b in zip(prev, cur)) / len(cur)
    return hamming > config.DEDUP_HASH_BITS or diff > config.DEDUP_PIXEL_DIFF


def _encode_sig(gray: bytes) -> str:
    """签名（灰度字节串）→ state.json 可存的 base64。"""
    return base64.b64encode(gray).decode("ascii")


def _decode_sig(data) -> bytes | None:
    """state.json 里的签名还原为字节串；缺失/损坏/尺寸不符返回 None（当无上帧处理）。"""
    if not isinstance(data, str):
        return None
    try:
        gray = base64.b64decode(data)
    except ValueError:
        return None
    if len(gray) != config.DEDUP_SIG_SIZE[0] * config.DEDUP_SIG_SIZE[1]:
        return None
    return gray


def _report_date(name: str):
    """报告文件名 → (开始日期, 结束日期)；解析失败返回 None（不删，保守）。

    日报当天开始当天结束；周报按周一~周日（保留判断用结束日，避免
    覆盖到保留窗口尾部的周报被过早删掉）。
    """
    m = re.match(r"日报-(\d{4}-\d{2}-\d{2})\.md", name)
    if m:
        day = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        return day, day
    m = re.match(r"周报-(\d{4})-W(\d{1,2})\.md", name)
    if m:
        monday = datetime.fromisocalendar(int(m.group(1)), int(m.group(2)), 1).date()
        return monday, monday + timedelta(days=6)
    return None


def cleanup_expired() -> None:
    """按设置保留天数清理过期记录与报告（0 = 永久保留，不清理）。

    每天最多执行一次，节流标记用独立文件 .last_cleanup（存日期字符串）——
    不能写进 state.json：capture 的 save_state 是整体覆盖，并存字段会丢。
    """
    days = config.SETTINGS.get("retention_days", 0)
    marker = config.DATA_DIR / ".last_cleanup"
    today = datetime.now().date()
    # 截图兜底清扫：正常流程分析完即删（finally 保证），这里只处理
    # 进程被强杀/崩溃留下的孤儿文件，超 1 天无条件删除（与保留天数设置无关）
    if config.SCREENSHOTS_DIR.exists():
        cutoff_ts = time.time() - 86400
        for p in config.SCREENSHOTS_DIR.glob("*.png"):
            try:
                if p.stat().st_mtime < cutoff_ts:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
    if not days:
        return
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == today.isoformat():
            return
    except OSError as e:
        _logger.warning("清理节流标记读取失败（本次继续执行清理）: %s", e)
    cutoff = today - timedelta(days=days)
    removed = 0
    for p in config.RAW_DIR.glob("*.jsonl"):
        try:
            day = datetime.strptime(p.stem, "%Y-%m-%d").date()
        except ValueError:
            continue  # 文件名不是日期（垃圾文件），跳过
        if day < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    # 只有 .md 没有 .jsonl 的日子也要清理（如 jsonl 已删/手动编辑过的时间线）
    for p in config.RECORDS_DIR.glob("*.md"):
        try:
            day = datetime.strptime(p.stem, "%Y-%m-%d").date()
        except ValueError:
            continue  # 文件名不是日期（垃圾文件），跳过
        if day < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    for p in config.REPORTS_DIR.glob("*.md"):
        span = _report_date(p.name)
        if span and span[1] < cutoff:  # 报告覆盖期整体早于窗口 → 删
            p.unlink(missing_ok=True)
            removed += 1
    if config.USAGE_DIR.exists():  # 应用使用时长采样数据同样受保留天数约束
        for p in config.USAGE_DIR.glob("*.jsonl"):
            try:
                day = datetime.strptime(p.stem, "%Y-%m-%d").date()
            except ValueError:
                continue  # 文件名不是日期（垃圾文件），跳过
            if day < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
    try:
        marker.write_text(today.isoformat(), encoding="utf-8")
    except OSError as e:
        _logger.warning("清理节流标记写入失败（下次截屏会重试）: %s", e)
    if removed:
        log(f"数据清理：已删除 {removed} 个过期文件（保留 {days} 天）")


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


def main(force: bool = False) -> int:
    """截屏记录主流程；force=True 时跳过空闲检测与画面去重（手动截屏）。"""
    cleanup_expired()  # 顺带按保留天数清理过期数据（每天一次）
    if not config.ANALYZE_API_KEY:
        log("未配置模型服务 API Key，请在应用设置页或 .env 中填写后重试")
        return 1
    if not config.ANALYZE_BASE_URL or not config.ANALYZE_MODEL:
        log("自定义模型未配置完整（接口地址/模型名称），请在设置页「模型服务」中填写")
        return 1

    if not force and config.IDLE_ENABLED and last_input_idle_seconds() > config.IDLE_MINUTES * 60:
        log(f"鼠标空闲超过 {config.IDLE_MINUTES} 分钟，跳过本次")
        return 0

    config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    # 前台窗口元数据必须在隐藏自身窗口之前采样：隐藏会改变前台归属，采晚了就采到别的窗口。
    # 自己（dailylog.exe/pythonw.exe）在前台时，隐藏后画面已换成别的窗口，元数据不可信，弃用。
    fg_process, fg_title = usage.foreground_window()
    if fg_process == Path(sys.executable).name.lower():
        fg_process, fg_title = None, ""
        log("前台是 dailylog 自身，跳过前台元数据")
    png_path = None
    try:
        with mss.MSS() as sct:
            monitor = sct.monitors[config.MONITOR_INDEX]
            hidden = _hide_app_windows()  # 隐藏应用自身窗口，避免其界面进入截图
            try:
                raw = sct.grab(monitor)

                if is_black_screen(raw.raw):
                    log("屏幕为黑屏/睡眠，跳过本次")
                    return 0

                rgb = raw.rgb  # 签名与保存 PNG 复用同一份 RGB 字节
                state = load_state()
                sig = _screen_signature(rgb, raw.size, _workarea_crop_box(monitor))
                prev_sig = _decode_sig(state.get("last_sig"))
                # 上次分析失败（last_failed）时放行：即使画面未变也重试，避免去重把重试挡掉
                # dedup_enabled=False（设置页"跳过重复画面"关闭）时不去重，每次都识别
                if (not force and config.DEDUP_ENABLED and prev_sig is not None
                        and not state.get("last_failed") and not _screen_changed(prev_sig, sig)):
                    log("画面无变化，跳过本次")
                    return 0

                png_path = config.SCREENSHOTS_DIR / f"{ts:%Y%m%d_%H%M%S}.png"
                mss.tools.to_png(rgb, raw.size, output=str(png_path))
            finally:
                _show_app_windows(hidden)  # 截图已保存，立即恢复被隐藏的窗口
    except Exception as e:
        log(f"截屏失败: {e}")
        if png_path and png_path.exists():
            png_path.unlink(missing_ok=True)
        return 1

    # 当日已有待办：随分析请求带上，让模型跳过重复/进展类内容，避免待办碎片化
    existing_todos = []
    raw_path = config.RAW_DIR / f"{ts:%Y-%m-%d}.jsonl"
    if raw_path.exists():
        try:
            for line in raw_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                todo = json.loads(line).get("todo")
                if todo:
                    existing_todos.append(str(todo))
        except (OSError, json.JSONDecodeError):
            pass
    record = None
    try:
        for attempt in range(config.MAX_RETRIES + 1):
            try:
                foreground = " / ".join(p for p in (fg_process, fg_title.strip()) if p)
                record = analyze.call_analyze(analyze.encode_image(png_path), existing_todos, foreground=foreground)
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
        save_state({"last_sig": _encode_sig(sig), "last_failed": True})
        return 1

    save_state({"last_sig": _encode_sig(sig)})  # 成功：整体覆盖 state.json，同时清除 last_failed 标记
    append_record(ts, record)
    log(f"已记录: {record['activity']} | {record['summary'][:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
