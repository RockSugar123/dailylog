"""桌面应用 Api 桥接：前端通过 window.pywebview.api 调用的方法都在这。

纯 Python，不依赖 pywebview，便于无 GUI 直测。返回结构均为 JSON 友好的 dict/list。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path

from dotenv import set_key

from core import analyze, backup, config, llm, summarize, todos, usage

TASK_NAME = "DailyLogCapture"
USAGE_TASK_NAME = "DailyLogUsage"
BACKUP_TASK_NAME = "DailyLogBackup"
BACKUP_WEEKDAY_CHOICES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
INTERVAL_CHOICES = (5, 10, 15, 30, 60)
IDLE_CHOICES = config.IDLE_CHOICES
RETENTION_CHOICES = config.RETENTION_CHOICES


def _write_settings(**overrides) -> None:
    """写 settings.json（保留其余键）并同步 config.SETTINGS。"""
    data = dict(config.SETTINGS)
    data.update(overrides)
    (config.DATA_DIR / "settings.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    config.SETTINGS.update(overrides)


def _task_command(flag: str = "--capture", script: str = "core/capture.py") -> str:
    """任务计划要执行的命令。打包后（frozen）运行 exe <flag>，开发期运行 pythonw <script>。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {flag}'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pyw}" "{config.BASE_DIR / script}"'


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


def task_is_enabled(name: str = TASK_NAME) -> bool:
    """查询任务计划是否启用。

    优先用任务计划 COM 接口；COM 失败时回退解析 schtasks XML 的 <Enabled> 元素
    （2026-08-02 实测本系统 XML 含该元素，与旧注释相反；元素缺失按任务计划
    默认语义视为启用）。禁止裸返回 False —— 否则 toggle 会基于错误状态决策。
    """
    _logger = config.setup_logging()
    own_com = _com_init()
    try:
        import win32com.client  # noqa: PLC0415
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        task = scheduler.GetFolder("\\").GetTask(name)
        return bool(task.Enabled)
    except Exception as e:  # noqa: BLE001
        _logger.warning("查询任务启用状态 COM 失败，回退 XML: %s", e)
    finally:
        if own_com:
            import pythoncom  # noqa: PLC0415
            pythoncom.CoUninitialize()
    try:
        xml = _schtasks("/query", "/tn", name, "/xml")
        m = re.search(r"<Enabled>(true|false)</Enabled>", xml)
        return m.group(1) == "true" if m else True
    except RuntimeError as e:
        _logger.warning("XML 查询任务失败（按已停用处理）: %s", e)
        return False  # 任务不存在/查询失败


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
        try:
            return pythoncom.CoInitialize() == 0  # S_OK
        except pythoncom.com_error as e:
            # 线程已以 MTA 初始化（pywebview 桥线程等）时 CoInitialize(STA) 抛
            # RPC_E_CHANGED_MODE(0x80010106)：COM 实际可用，直接继续、勿反初始化
            if e.hresult == -2147417850:  # RPC_E_CHANGED_MODE
                return False
            raise
    except Exception:  # noqa: BLE001
        return False


def _set_task_enabled(enabled: bool, name: str = TASK_NAME) -> None:
    """启用/停用定时任务。用 COM 进程内直连（毫秒级），schtasks 兜底。

    schtasks.exe 是独立进程 + 服务往返，慢（1~3s），在"退出程序"路径上不可接受。
    """
    _logger = config.setup_logging()
    own_com = _com_init()
    try:
        import win32com.client  # noqa: PLC0415
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        task = scheduler.GetFolder("\\").GetTask(name)
        task.Enabled = enabled
    except Exception as e:  # noqa: BLE001
        _logger.warning("任务启停 COM 失败，回退 schtasks: %s", e)
        try:
            _schtasks("/change", "/tn", name, "/enable" if enabled else "/disable")
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


def ensure_usage_task() -> None:
    """确保应用时长采样任务存在（应用启动时调用，幂等；创建即启用）。"""
    _schtasks("/create", "/tn", USAGE_TASK_NAME, "/tr",
              _task_command("--usage", "core/usage.py"),
              "/sc", "minute", "/mo", str(config.USAGE_INTERVAL_MINUTES), "/f")


def set_usage_enabled(enabled: bool) -> dict:
    """应用时长统计开关：写设置 + 创建/停用采样任务计划。"""
    enabled = bool(enabled)
    _write_settings(usage_enabled=enabled)
    config.USAGE_ENABLED = enabled
    if enabled:
        ensure_usage_task()
    else:
        _set_task_enabled(False, USAGE_TASK_NAME)
    return {"ok": True, "usage_enabled": enabled}


# ---------- 自动备份 ----------

def _backup_command() -> str:
    return _task_command("--backup", "core/backup.py")


def ensure_backup_task() -> None:
    """按当前设置（幂等）注册每周备份任务计划：/sc weekly /d 周X /st 整点。"""
    day = str(config.SETTINGS.get("backup_weekday", "SUN")).upper()
    if day not in BACKUP_WEEKDAY_CHOICES:
        day = "SUN"
    hour = int(config.SETTINGS.get("backup_hour", 12))
    _schtasks("/create", "/tn", BACKUP_TASK_NAME, "/tr", _backup_command(),
              "/sc", "weekly", "/d", day, "/st", f"{hour:02d}:00", "/f")


def persist_recording_choice(enabled: bool) -> None:
    """记录用户对定时记录开/停的选择（settings.json），供启动/恢复时遵守。"""
    _write_settings(recording_enabled=bool(enabled))


def _key_hint(key: str) -> str:
    """Key 的掩码提示（设置页展示用），如 sk-****abc4；绝不返回完整 Key。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


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
        try:
            day = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return []
        records = summarize.load_records(day)
        for rec in records:
            rec["label"] = config.ACTIVITY_LABELS.get(rec.get("activity", ""), "其他")
        return records

    def get_records_range(self, start: str, end: str) -> list:
        """日期范围（含首尾）内的全部时间线条目，按时间升序。"""
        start_d = datetime.strptime(start, "%Y-%m-%d")
        end_d = datetime.strptime(end, "%Y-%m-%d")
        records = []
        d = start_d
        while d <= end_d:
            records.extend(self.get_records(d.strftime("%Y-%m-%d")))
            d += timedelta(days=1)
        records.sort(key=lambda r: r.get("ts", ""))
        return records

    # ---------- 应用使用时长 ----------

    def get_usage_stats(self, scope: str, date: str = "") -> dict:
        """应用使用时长统计。scope ∈ day/week/month，date 为该周期内任意一天（YYYY-MM-DD）。"""
        from datetime import date as _date  # noqa: PLC0415
        try:
            day = _date.fromisoformat(date or datetime.now().strftime("%Y-%m-%d"))
        except ValueError:
            return {"ok": False, "error": "日期格式错误"}
        if scope == "week":
            start = day - timedelta(days=day.weekday())
            end = start + timedelta(days=6)
        elif scope == "month":
            start = day.replace(day=1)
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        else:
            start = end = day
        # 时段分布粒度：日视图按小时，周/月视图按天
        stats = usage.aggregate(start, end, granularity="hour" if scope == "day" else "day")
        stats.update({"ok": True, "scope": scope, "start": start.isoformat(), "end": end.isoformat(),
                      "days": (end - start).days + 1})
        return stats

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
        # name 来自前端，必须挡住 ..\..\ 形式的路径穿越
        if not re.fullmatch(r"[\w\-]+\.md", name or ""):
            return {"ok": False, "error": "非法的报告文件名"}
        path = config.REPORTS_DIR / name
        if not path.exists():
            return {"ok": False, "error": "报告不存在"}
        return {"ok": True, "name": name, "content": path.read_text(encoding="utf-8")}

    # ---------- 待办 ----------

    def get_todos(self) -> list:
        """全部待办（先增量同步时间线里的待办字段）：优先级高在前，同级新在前。"""
        todos.sync_from_records()
        items = todos.load()["items"]
        return sorted(sorted(items, key=lambda it: it.get("ts", ""), reverse=True),
                      key=lambda it: todos.PRIORITY_ORDER.get(it.get("priority"), 1))

    def add_todo(self, text: str, priority: str = "中") -> dict:
        """手动新建待办。"""
        return todos.add(text, priority)

    def set_todo_status(self, todo_id: str, status: str) -> dict:
        """切换待办状态（勾选完成 / 状态变更）。"""
        return todos.set_status(todo_id, status)

    def delete_todo(self, todo_id: str) -> dict:
        """删除一条待办。"""
        return todos.remove(todo_id)

    # ---------- 设置 ----------

    def get_config(self) -> dict:
        return {
            "interval_minutes": config.SETTINGS.get("interval_minutes", 10),
            "interval_choices": list(INTERVAL_CHOICES),
            "report_name": config.REPORT_NAME,
            "recording_enabled": task_is_enabled(),
            "next_capture": task_next_run(),
            "idle_enabled": bool(config.SETTINGS.get("idle_enabled", True)),
            "idle_minutes": config.SETTINGS.get("idle_minutes", 5),
            "idle_choices": list(config.IDLE_CHOICES),
            "retention_days": config.SETTINGS.get("retention_days", 0),
            "retention_choices": list(config.RETENTION_CHOICES),
            "dedup_enabled": bool(config.SETTINGS.get("dedup_enabled", True)),
            "enter_capture_enabled": bool(config.SETTINGS.get("enter_capture_enabled", False)),
            "enter_capture_interval": config.SETTINGS.get("enter_capture_interval", 15),
            "enter_interval_choices": list(config.ENTER_INTERVAL_CHOICES),
            "usage_enabled": bool(config.SETTINGS.get("usage_enabled", True)),
            "backup_enabled": bool(config.SETTINGS.get("backup_enabled", True)),
            "backup_dir": str(config.SETTINGS.get("backup_dir", "")),
            "backup_weekday": str(config.SETTINGS.get("backup_weekday", "SUN")).upper(),
            "backup_hour": int(config.SETTINGS.get("backup_hour", 12)),
            "backup_keep": int(config.SETTINGS.get("backup_keep", 5)),
            "backup_weekday_choices": list(BACKUP_WEEKDAY_CHOICES),
            "theme": config.SETTINGS.get("theme", "glass"),
            "test_interval_seconds": config.SETTINGS.get("test_interval_seconds"),
            "model_presets": [
                {"id": pid, "label": p["label"], "base_url": p["base_url"],
                 "default_model": p["default_model"], "hint": p["hint"]}
                for pid, p in config.MODEL_PRESETS.items()
            ],
            "provider": config.MODEL_PROVIDER,
            "provider_label": config.MODEL_PRESETS[config.MODEL_PROVIDER]["label"],
            "base_url": config.MODEL_BASE_URL,
            "model": config.MODEL_NAME,
            "has_key": bool(config.MODEL_API_KEY),
            "key_hint": _key_hint(config.MODEL_API_KEY),
        }

    def get_logs(self, limit: int = 300) -> dict:
        """读运行日志尾部（最新在前），供左侧日志页查看报错原因。"""
        path = config.DATA_DIR / "dailylog.log"
        if not path.exists():
            return {"ok": True, "logs": []}
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return {"ok": False, "error": str(e)}
        logs = []
        for line in lines[-limit:]:
            parts = line.split(" ", 2)  # "2026-08-04 18:04:40 INFO 消息"
            if len(parts) == 3 and len(parts[0]) == 10 and len(parts[1]) == 8:
                level, _, msg = parts[2].partition(" ")
                logs.append({"ts": f"{parts[0]} {parts[1]}", "level": level, "msg": msg})
            else:
                logs.append({"ts": "", "level": "", "msg": line})
        logs.reverse()  # 最新在前
        return {"ok": True, "logs": logs}

    def set_test_interval(self, seconds: int) -> dict:
        """测试用：秒级截屏间隔（配合验证用，用完在设置页改回分钟即可清除）。"""
        try:
            apply_test_interval(int(seconds))
            return {"ok": True, "test_interval_seconds": int(seconds)}
        except (ValueError, RuntimeError) as e:
            return {"ok": False, "error": str(e)}

    def get_model_service(self) -> dict:
        """设置页加载时回显全部供应商的模型服务配置（含各自 Key）。

        前端缓存后切换供应商下拉时即时联动回显。纯本地应用：Key 本就明文存于
        用户磁盘的 .env，回显到用户自己的界面没有额外暴露面。刻意不放进
        轮询的 get_config，避免反复传输。
        """
        services = {}
        for pid, preset in config.MODEL_PRESETS.items():
            svc = config.MODEL_SERVICES.get(pid)
            if not isinstance(svc, dict):
                svc = {}
            services[pid] = {
                # 只回显用户填过的模型名（未填为空白，占位提示里展示默认值）
                "model": str(svc.get("model", "")).strip(),
                "base_url": str(svc.get("base_url", "")).strip() if pid == "custom" else preset["base_url"],
                "key": config.model_key_for(pid),
            }
        return {"ok": True, "provider": config.MODEL_PROVIDER, "services": services}

    def save_model_service(self, provider: str, model: str, key: str = "",
                           base_url: str = "") -> dict:
        """保存某供应商的模型服务：模型名写 settings.json 的 model_services，Key 写 .env。

        各供应商的模型名/Key 相互独立（.env 键为 MODEL_KEY_<PROVIDER>）。
        key 传空表示不修改该供应商的 Key。预设供应商的 base_url 以代码里的
        官方端点为准；custom 用前端传的地址。保存即切换生效并同步本进程 config。
        """
        _logger = config.setup_logging()
        provider = (provider or "").strip()
        preset = config.MODEL_PRESETS.get(provider)
        if not preset:
            return {"ok": False, "error": f"未知供应商: {provider}"}
        model = (model or "").strip() or preset["default_model"]
        if not model:
            return {"ok": False, "error": "请填写模型名称"}
        if provider == "custom":
            base_url = (base_url or "").strip().rstrip("/")
            if not base_url.startswith(("http://", "https://")):
                return {"ok": False, "error": "自定义供应商需填写以 http(s):// 开头的接口地址"}
        key = (key or "").strip()
        if key:
            env_name = f"MODEL_KEY_{provider.upper()}"
            try:
                set_key(str(config.DATA_DIR / ".env"), env_name, key)
            except OSError as e:
                _logger.error("写入 .env 失败: %s", e)
                return {"ok": False, "error": f"写入 .env 失败：{e}"}
            os.environ[env_name] = key  # .env 只在启动时加载，同步进程环境供 model_key_for 读取
        # 更新该供应商的配置（其余供应商不动）；顺带清理旧版统一键
        services = {k: dict(v) for k, v in config.MODEL_SERVICES.items() if isinstance(v, dict)}
        svc = services.setdefault(provider, {})
        svc["model"] = model
        if provider == "custom":
            svc["base_url"] = base_url
        else:
            svc.pop("base_url", None)
        data = dict(config.SETTINGS)
        data["model_provider"] = provider
        data["model_services"] = services
        legacy_gone = data.pop("model_name", None) is not None or data.pop("model_base_url", None) is not None
        config.SETTINGS.pop("model_name", None)   # config.SETTINGS 是 _write_settings 的
        config.SETTINGS.pop("model_base_url", None)  # 合并源，需同步移除才能真正落盘删除
        _write_settings(**data)
        config.MODEL_SERVICES.clear()
        config.MODEL_SERVICES.update(services)
        config.MODEL_PROVIDER = provider
        config._apply_model_service()
        # 只记供应商与模型名，不记 Key
        _logger.info("模型服务已更新：%s / %s%s", provider, model,
                     "（清理旧版配置）" if legacy_gone else "")
        return {
            "ok": True,
            "provider": provider,
            "provider_label": preset["label"],
            "base_url": config.MODEL_BASE_URL,
            "model": config.MODEL_NAME,
            "has_key": bool(config.MODEL_API_KEY),
            "key_hint": _key_hint(config.MODEL_API_KEY),
        }

    def test_model_connection(self, provider: str = "", model: str = "",
                              key: str = "", base_url: str = "") -> dict:
        """设置页"测试连接"：对表单当前草稿（供应商/模型/Key）发一条极短消息验证连通性。

        Key/模型留空时回退到该供应商已保存值（再回退预设默认模型），
        方便只改了供应商就想先测的场景。
        """
        _logger = config.setup_logging()
        provider = (provider or "").strip() or config.MODEL_PROVIDER
        preset = config.MODEL_PRESETS.get(provider)
        if not preset:
            return {"ok": False, "error": f"未知供应商: {provider}"}
        if not model or not str(model).strip():
            svc = config.MODEL_SERVICES.get(provider)
            model = (str(svc.get("model", "")).strip()
                     if isinstance(svc, dict) else "") or preset["default_model"]
        model = str(model).strip()
        if not model:
            return {"ok": False, "error": "请先填写模型名称"}
        if provider == "custom":
            base_url = (base_url or "").strip().rstrip("/")
            if not base_url.startswith(("http://", "https://")):
                return {"ok": False, "error": "自定义供应商需先填写接口地址"}
        else:
            base_url = preset["base_url"]
        key = (key or "").strip() or config.model_key_for(provider)
        if not key:
            return {"ok": False, "error": "尚未配置 API Key，请先填写并保存"}
        result = llm.test_chat(base_url, key, model)
        if result.get("ok"):
            _logger.info("模型服务测试通过：%s / %s（%d ms）",
                         provider, model, result.get("latency_ms", 0))
        else:
            _logger.warning("模型服务测试失败（%s / %s）：%s",
                            provider, model, result.get("error", ""))
        return result

    def clear_test_interval(self) -> dict:
        """清除测试间隔（恢复任务计划驱动的分钟级记录）。"""
        data = dict(config.SETTINGS)
        data.pop("test_interval_seconds", None)
        _write_settings(**data)
        return {"ok": True}

    def toggle_recording(self) -> dict:
        """截屏记录总开关（标题栏/托盘共用）：启用↔停用定时记录，并持久化选择。"""
        if task_is_enabled():
            disable_task()
            enabled = False
        else:
            enable_task()
            enabled = True
        persist_recording_choice(enabled)
        return {"ok": True, "recording_enabled": enabled}

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

    def set_retention(self, days: int) -> dict:
        """设置本地记录保留天数（0 = 永久保留）。"""
        days = int(days)
        if days not in RETENTION_CHOICES:
            return {"ok": False, "error": f"保留天数必须是 {RETENTION_CHOICES} 之一"}
        _write_settings(retention_days=days)
        return {"ok": True, "retention_days": days}

    def set_interval(self, minutes: int) -> dict:
        try:
            apply_interval(int(minutes))
            return {"ok": True, "interval_minutes": int(minutes)}
        except (ValueError, RuntimeError) as e:
            return {"ok": False, "error": str(e)}

    def set_dedup(self, enabled: bool) -> dict:
        """跳过重复画面开关（capture.py 的 md5 去重，默认开）。"""
        _write_settings(dedup_enabled=bool(enabled))
        config.DEDUP_ENABLED = bool(enabled)
        return {"ok": True, "dedup_enabled": bool(enabled)}

    def set_theme(self, theme: str) -> dict:
        """界面皮肤：glass=玻璃拟态 / paper=纸面编辑部 / journal=暖光手账 /
        terminal=墨绿终端 / abyss=深海蓝调 / film=胶片暗房 / mint=薄荷汽水 / sakura=樱吹雪。"""
        if theme not in ("glass", "paper", "journal", "terminal", "abyss", "film", "mint", "sakura"):
            return {"ok": False, "error": f"未知皮肤: {theme}"}
        _write_settings(theme=theme)
        return {"ok": True, "theme": theme}

    def set_enter_capture(self, enabled: bool, seconds: int) -> dict:
        """回车键快速记录：全局监听开关 + 间隔内只记录第一次（秒）。"""
        seconds = int(seconds)
        if seconds not in config.ENTER_INTERVAL_CHOICES:
            return {"ok": False, "error": f"间隔必须是 {config.ENTER_INTERVAL_CHOICES} 之一"}
        _write_settings(enter_capture_enabled=bool(enabled), enter_capture_interval=seconds)
        config.ENTER_CAPTURE_ENABLED = bool(enabled)
        config.ENTER_CAPTURE_INTERVAL = seconds
        return {"ok": True, "enter_capture_enabled": bool(enabled), "enter_capture_interval": seconds}

    # ---------- 数据管理 ----------

    # 导出/导入备份里允许包含的设置键（API Key 在 .env，永不进备份）
    EXPORT_SETTING_KEYS = (
        "interval_minutes", "report_name", "idle_enabled", "idle_minutes",
        "retention_days", "recording_enabled", "dedup_enabled",
        "enter_capture_enabled", "enter_capture_interval", "usage_enabled", "theme",
        "model_provider", "model_services",
        "backup_enabled", "backup_dir", "backup_weekday", "backup_hour", "backup_keep",
    )

    def export_data(self, path: str) -> dict:
        """导出 JSON 备份：时间线 jsonl + 当日 md + 报告 + 待办 + 安全设置键。"""
        try:
            records = {}
            if config.RAW_DIR.exists():
                for p in config.RAW_DIR.glob("*.jsonl"):
                    records[p.stem] = p.read_text(encoding="utf-8", errors="replace")
            md_files = {}
            if config.RECORDS_DIR.exists():
                for p in config.RECORDS_DIR.glob("*.md"):
                    md_files[p.name] = p.read_text(encoding="utf-8", errors="replace")
            reports = {}
            if config.REPORTS_DIR.exists():
                for p in config.REPORTS_DIR.glob("*.md"):
                    reports[p.name] = p.read_text(encoding="utf-8", errors="replace")
            backup = {
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "app": "dailylog",
                "version": 1,
                "settings": {k: config.SETTINGS.get(k) for k in self.EXPORT_SETTING_KEYS},
                "records": records,   # 日期 → jsonl 内容
                "md": md_files,       # 文件名 → 内容（当日 md 时间线）
                "reports": reports,   # 文件名 → 内容
                "todos": todos.load(),
            }
            Path(path).write_text(
                json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            return {"ok": True, "path": path}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def import_data(self, path: str) -> dict:
        """从备份恢复：records/md/报告/待办/设置。已存在的文件跳过（不覆盖当前数据）。"""
        try:
            backup = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": f"备份文件读取失败: {e}"}
        if not isinstance(backup.get("records"), dict):
            return {"ok": False, "error": "不是有效的 dailylog 备份文件"}
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        config.RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        restored = {"records": 0, "md": 0, "reports": 0}
        for date, content in backup.get("records", {}).items():
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and not (config.RAW_DIR / f"{date}.jsonl").exists():
                (config.RAW_DIR / f"{date}.jsonl").write_text(content, encoding="utf-8")
                restored["records"] += 1
        for name, content in backup.get("md", {}).items():
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name) and not (config.RECORDS_DIR / name).exists():
                (config.RECORDS_DIR / name).write_text(content, encoding="utf-8")
                restored["md"] += 1
        for name, content in backup.get("reports", {}).items():
            if name.endswith(".md") and not (config.REPORTS_DIR / name).exists():
                (config.REPORTS_DIR / name).write_text(content, encoding="utf-8")
                restored["reports"] += 1
        # 待办整表恢复（备份即快照）；设置合并（只写备份里存在的安全键）
        if isinstance(backup.get("todos"), dict) and isinstance(backup["todos"].get("items"), list):
            todos.save(backup["todos"])
        merged = {k: backup["settings"][k] for k in self.EXPORT_SETTING_KEYS if k in backup.get("settings", {})}
        if merged:
            _write_settings(**merged)
        return {"ok": True, **restored}

    def clear_data(self) -> dict:
        """清除历史数据：records/、reports/、截图、日志、待办；保留 .env 与 settings.json。"""
        _logger = config.setup_logging()
        removed = {"records": 0, "reports": 0}
        try:
            for p in list(config.RAW_DIR.glob("*.jsonl")) + list(config.RECORDS_DIR.glob("*.md")):
                p.unlink(missing_ok=True)
                removed["records"] += 1
            for p in config.REPORTS_DIR.glob("*.md"):
                p.unlink(missing_ok=True)
                removed["reports"] += 1
            for p in config.USAGE_DIR.glob("*.jsonl"):  # 应用使用时长数据一并清除
                p.unlink(missing_ok=True)
            for p in config.SCREENSHOTS_DIR.glob("*.png"):  # 孤儿截图一并清除
                p.unlink(missing_ok=True)
            for p in config.DATA_DIR.glob("dailylog.log*"):
                p.unlink(missing_ok=True)
            config.TODOS_FILE.unlink(missing_ok=True)
            config.STATE_FILE.unlink(missing_ok=True)
        except OSError as e:
            return {"ok": False, "error": str(e)}
        _logger.info("数据管理：已清除本地数据（%d 条记录、%d 份报告、日志与待办）",
                     removed["records"], removed["reports"])
        return {"ok": True, **removed}

    def set_backup_settings(self, enabled: bool = None, backup_dir: str = None,
                            weekday: str = None, hour: int = None, keep: int = None) -> dict:
        """写备份设置并同步任务计划：开启且已选目录则注册（幂等），否则停用任务。"""
        _logger = config.setup_logging()
        updates = {}
        if enabled is not None:
            updates["backup_enabled"] = bool(enabled)
        if backup_dir is not None:
            updates["backup_dir"] = str(backup_dir).strip()
        if weekday is not None:
            weekday = str(weekday).upper()
            if weekday not in BACKUP_WEEKDAY_CHOICES:
                return {"ok": False, "error": f"星期必须是 {BACKUP_WEEKDAY_CHOICES} 之一"}
            updates["backup_weekday"] = weekday
        if hour is not None:
            if not 0 <= int(hour) <= 23:
                return {"ok": False, "error": "小时必须在 0-23 之间"}
            updates["backup_hour"] = int(hour)
        if keep is not None:
            if not 1 <= int(keep) <= 52:
                return {"ok": False, "error": "保留份数必须在 1-52 之间"}
            updates["backup_keep"] = int(keep)
        _write_settings(**updates)
        enabled = bool(config.SETTINGS.get("backup_enabled", True))
        has_dir = bool(str(config.SETTINGS.get("backup_dir", "")).strip())
        try:
            if enabled and has_dir:
                ensure_backup_task()
            else:
                _set_task_enabled(False, BACKUP_TASK_NAME)
        except RuntimeError as e:
            _logger.error("自动备份任务计划注册失败: %s", e)
            return {"ok": False, "error": f"任务计划注册失败: {e}"}
        _logger.info("自动备份设置已更新: %s", updates)
        return {"ok": True}

    def run_backup_now(self) -> dict:
        """设置页"立即备份"：同步执行打包（数据量小，秒级完成）。"""
        return backup.run_backup()

    def get_backup_info(self) -> dict:
        """备份设置 + 上次执行结果（backup_state.json），供设置页展示。"""
        state = {}
        state_file = config.DATA_DIR / "backup_state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        return {
            "ok": True,
            "enabled": bool(config.SETTINGS.get("backup_enabled", True)),
            "dir": str(config.SETTINGS.get("backup_dir", "")),
            "weekday": str(config.SETTINGS.get("backup_weekday", "SUN")).upper(),
            "hour": int(config.SETTINGS.get("backup_hour", 12)),
            "keep": int(config.SETTINGS.get("backup_keep", 5)),
            "weekday_choices": list(BACKUP_WEEKDAY_CHOICES),
            "last": state,
        }

    def db_stats(self) -> dict:
        """当前本地数据统计：容量 / 时间线条数 / 报告数 / 日志条数。"""
        total = timeline_count = 0
        if config.RAW_DIR.exists():
            for p in config.RAW_DIR.glob("*.jsonl"):
                try:
                    total += p.stat().st_size
                    timeline_count += sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
        report_count = 0
        if config.REPORTS_DIR.exists():
            for p in config.REPORTS_DIR.glob("*.md"):
                try:
                    total += p.stat().st_size
                    report_count += 1
                except OSError:
                    continue
        if config.RECORDS_DIR.exists():
            for p in config.RECORDS_DIR.glob("*.md"):
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
        log_count = 0
        for p in config.DATA_DIR.glob("dailylog.log*"):  # 日志在 data/ 下（BASE_DIR 是旧路径，已废弃）
            try:
                total += p.stat().st_size
                if p.name == "dailylog.log":
                    log_count = sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        return {
            "size_mb": round(total / 1024 / 1024, 2),
            "size_kb": round(total / 1024, 1),
            "timeline_count": timeline_count,
            "report_count": report_count,
            "log_count": log_count,
        }


