"""桌面应用 Api 桥接：前端通过 window.pywebview.api 调用的方法都在这。

纯 Python，不依赖 pywebview，便于无 GUI 直测。返回结构均为 JSON 友好的 dict/list。
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path

import analyze
import config
import summarize

TASK_NAME = "DailyLogCapture"
INTERVAL_CHOICES = (5, 10, 15, 30, 60)
IDLE_CHOICES = config.IDLE_CHOICES


def _write_settings(**overrides) -> None:
    """写 settings.json（保留其余键）并同步 config.SETTINGS。"""
    data = dict(config.SETTINGS)
    data.update(overrides)
    (config.BASE_DIR / "settings.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    config.SETTINGS.update(overrides)


def _task_command() -> str:
    """任务计划要执行的命令。打包后（frozen）运行 exe --capture，开发期运行 pythonw capture.py。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --capture'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pyw}" "{config.BASE_DIR / "capture.py"}"'


def _schtasks(*args: str) -> str:
    """执行 schtasks，返回 stdout+stderr。文本输出是 GBK，XML 输出是 UTF-16，按 BOM 自动识别。"""
    proc = subprocess.run(
        ["schtasks", *args],
        capture_output=True, timeout=30,
        # GUI 进程 spawn 控制台子进程时默认会闪黑色控制台窗口，必须抑制
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    data = proc.stdout + proc.stderr
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        out = data.decode("utf-16", errors="replace")
    else:
        out = data.decode("gbk", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"schtasks 失败: {out.strip()[:200]}")
    return out


def task_next_run() -> str:
    """下一次定时截屏时间（HH:MM）。

    从任务 XML 的 StartBoundary + Interval 推算下一次触发（时间网格法）。
    不用 COM 的 NextRunTime：win32com 在 PyInstaller 打包环境下对 VT_DATE 属性转换失败。
    """
    try:
        xml = _schtasks("/query", "/tn", TASK_NAME, "/xml")
        sb = re.search(r"<StartBoundary>([^<]+)</StartBoundary>", xml)
        if not sb:
            return ""
        start = datetime.strptime(sb.group(1), "%Y-%m-%dT%H:%M:%S")
        m = re.search(r"<Interval>PT(?:(\d+)M|(\d+)S)</Interval>", xml)
        if m:
            total_sec = (int(m.group(1)) * 60) if m.group(1) else int(m.group(2))
        else:
            total_sec = config.SETTINGS.get("interval_minutes", 10) * 60
        now = datetime.now()
        if now < start:
            nxt = start
        else:
            elapsed_sec = (now - start).total_seconds()
            nxt = start + timedelta(seconds=ceil(elapsed_sec / total_sec) * total_sec)
        return nxt.strftime("%H:%M:%S" if total_sec < 60 else "%H:%M")
    except Exception:  # noqa: BLE001
        return ""


def task_is_enabled() -> bool:
    """查询任务计划是否启用。

    用任务计划 COM 接口（schtasks 的 XML 导出在此系统上省略 Disabled 元素，文本输出无状态列，均不可靠）。
    """
    own_com = _com_init()
    try:
        import win32com.client  # noqa: PLC0415
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        task = scheduler.GetFolder("\\").GetTask(TASK_NAME)
        return bool(task.Enabled)
    except Exception:  # noqa: BLE001
        return False
    finally:
        if own_com:
            import pythoncom  # noqa: PLC0415
            pythoncom.CoUninitialize()


def apply_interval(minutes: int) -> None:
    """写入 settings.json 并以新间隔重建任务计划（含启用）。"""
    if minutes not in INTERVAL_CHOICES:
        raise ValueError(f"间隔必须是 {INTERVAL_CHOICES} 之一")
    data = dict(config.SETTINGS)
    data["interval_minutes"] = minutes
    data.pop("test_interval_seconds", None)  # 切回分钟时清除测试间隔
    _write_settings(**data)
    _schtasks("/create", "/tn", TASK_NAME, "/tr", _task_command(),
              "/sc", "minute", "/mo", str(minutes), "/f")


def apply_test_interval(seconds: int) -> None:
    """测试用：秒级截屏间隔。

    任务计划器的 Repetition 最小 1 分钟（schema 限制），秒级只能由应用进程内的
    测试循环驱动（见 app.py run_test_loop）；任务计划本身保持分钟级不动。
    """
    _write_settings(test_interval_seconds=int(seconds))


def _com_init() -> bool:
    """初始化当前线程的 COM（pywin32 要求每个线程显式初始化）。

    返回 True 表示由本函数完成初始化（调用方需在 finally 中 CoUninitialize），
    False 表示线程早已初始化（不要反初始化）。
    """
    try:
        import pythoncom  # noqa: PLC0415
        return pythoncom.CoInitialize() == 0  # S_OK
    except Exception:  # noqa: BLE001
        return False


def _set_task_enabled(enabled: bool) -> None:
    """启用/停用定时记录。用 COM 进程内直连（毫秒级），schtasks 兜底。

    schtasks.exe 是独立进程 + 服务往返，慢（1~3s），在"退出程序"路径上不可接受。
    """
    _logger = config.setup_logging()
    own_com = _com_init()
    try:
        import win32com.client  # noqa: PLC0415
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        task = scheduler.GetFolder("\\").GetTask(TASK_NAME)
        task.Enabled = enabled
    except Exception as e:  # noqa: BLE001
        _logger.warning("任务启停 COM 失败，回退 schtasks: %s", e)
        try:
            _schtasks("/change", "/tn", TASK_NAME, "/enable" if enabled else "/disable")
        except RuntimeError as e2:
            _logger.error("schtasks 启停也失败: %s", e2)
    finally:
        if own_com:
            import pythoncom  # noqa: PLC0415
            pythoncom.CoUninitialize()


def enable_task() -> None:
    """启用定时记录（应用启动时调用，幂等）。"""
    _set_task_enabled(True)


def disable_task() -> None:
    """停用定时记录（托盘"退出程序"时调用）。"""
    _set_task_enabled(False)


class Api:
    """暴露给前端的方法。pywebview 桥会自动把返回值 JSON 序列化给 JS。"""

    # ---------- 时间线 ----------

    def get_dates(self) -> list:
        """有记录的日期列表（降序）。"""
        if not config.RAW_DIR.exists():
            return []
        return sorted((p.stem for p in config.RAW_DIR.glob("*.jsonl")), reverse=True)

    def get_records(self, date: str) -> list:
        """某天的全部时间线条目（按时间排序，含分类中文标签）。"""
        path = config.RAW_DIR / f"{date}.jsonl"
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec["label"] = config.ACTIVITY_LABELS.get(rec.get("activity", ""), "其他")
            records.append(rec)
        records.sort(key=lambda r: r.get("ts", ""))
        return records

    def get_records_range(self, start: str, end: str) -> list:
        """日期范围（含首尾）内的全部时间线条目，按时间升序。"""
        from datetime import timedelta  # noqa: PLC0415
        start_d = datetime.strptime(start, "%Y-%m-%d")
        end_d = datetime.strptime(end, "%Y-%m-%d")
        records = []
        d = start_d
        while d <= end_d:
            records.extend(self.get_records(d.strftime("%Y-%m-%d")))
            d += timedelta(days=1)
        records.sort(key=lambda r: r.get("ts", ""))
        return records

    # ---------- 报告 ----------

    def generate_report(self, kind: str, date: str = "") -> dict:
        """生成日报(kind=day)/周报(kind=week)，date 为 YYYY-MM-DD，缺省今天。

        注意：空日期必须补为今天，否则周报分支（if week:）会把空串当假值误走日报分支。
        """
        try:
            date = date or datetime.now().strftime("%Y-%m-%d")
            path, content = summarize.generate_report(
                day=date if kind == "day" else None,
                week=date if kind == "week" else None,
            )
            return {"ok": True, "path": path, "content": content}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def list_reports(self) -> list:
        """已生成的报告列表（降序，含文件名与生成时间）。"""
        if not config.REPORTS_DIR.exists():
            return []
        items = []
        for p in config.REPORTS_DIR.glob("*.md"):
            items.append({
                "name": p.name,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        items.sort(key=lambda x: x["name"], reverse=True)
        return items

    def get_report(self, name: str) -> dict:
        """读取一份已生成的报告内容。"""
        path = config.REPORTS_DIR / name
        if not path.exists():
            return {"ok": False, "error": "报告不存在"}
        return {"ok": True, "name": name, "content": path.read_text(encoding="utf-8")}

    # ---------- 设置 ----------

    def get_config(self) -> dict:
        return {
            "interval_minutes": config.SETTINGS.get("interval_minutes", 10),
            "interval_choices": list(INTERVAL_CHOICES),
            "report_name": config.REPORT_NAME,
            "analyze_model": config.ANALYZE_MODEL,
            "summary_model": config.SUMMARY_MODEL,
            "recording_enabled": task_is_enabled(),
            "next_capture": task_next_run(),
            "idle_enabled": bool(config.SETTINGS.get("idle_enabled", True)),
            "idle_minutes": config.SETTINGS.get("idle_minutes", 5),
            "idle_choices": list(config.IDLE_CHOICES),
            "test_interval_seconds": config.SETTINGS.get("test_interval_seconds"),
            "has_analyze_key": bool(config.DASHSCOPE_API_KEY),
            "has_summary_key": bool(config.DEEPSEEK_API_KEY),
        }

    def set_test_interval(self, seconds: int) -> dict:
        """测试用：秒级截屏间隔（配合验证用，用完在设置页改回分钟即可清除）。"""
        try:
            apply_test_interval(int(seconds))
            return {"ok": True, "test_interval_seconds": int(seconds)}
        except (ValueError, RuntimeError) as e:
            return {"ok": False, "error": str(e)}

    def clear_test_interval(self) -> dict:
        """清除测试间隔（恢复任务计划驱动的分钟级记录）。"""
        data = dict(config.SETTINGS)
        data.pop("test_interval_seconds", None)
        _write_settings(**data)
        return {"ok": True}

    def toggle_recording(self) -> dict:
        """截屏记录总开关（标题栏/托盘共用）：启用↔停用定时记录。"""
        if task_is_enabled():
            disable_task()
        else:
            enable_task()
        return {"ok": True, "recording_enabled": task_is_enabled()}

    def set_idle(self, enabled: bool, minutes: int) -> dict:
        """设置鼠标空闲暂停截屏：开关 + 阈值分钟。"""
        minutes = int(minutes)
        if minutes not in IDLE_CHOICES:
            return {"ok": False, "error": f"空闲分钟必须是 {IDLE_CHOICES} 之一"}
        _write_settings(idle_enabled=bool(enabled), idle_minutes=minutes)
        config.IDLE_ENABLED = bool(enabled)
        config.IDLE_MINUTES = minutes
        return {"ok": True, "idle_enabled": bool(enabled), "idle_minutes": minutes}

    def set_report_name(self, name: str) -> dict:
        """设置日报"汇报人"，写入 settings.json（保留其余配置）。"""
        name = (name or "").strip()
        _write_settings(report_name=name)
        config.REPORT_NAME = name
        return {"ok": True, "report_name": name}

    def set_interval(self, minutes: int) -> dict:
        try:
            apply_interval(int(minutes))
            return {"ok": True, "interval_minutes": int(minutes)}
        except (ValueError, RuntimeError) as e:
            return {"ok": False, "error": str(e)}

    # ---------- 手动记录 ----------

    def run_capture(self) -> dict:
        """立即执行一次截屏分析（托盘"开始记录"）。"""
        import capture
        code = capture.main()
        return {"ok": code == 0, "code": code}
