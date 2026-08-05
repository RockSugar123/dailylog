"""待办存储与时间线同步：records/todos.json 只由 GUI 进程读写。

条目结构：{id, text, status, priority, source, ts}
- status: 未开始 / 进行中 / 已完成 / 归档
- priority: 高 / 中 / 低
- source: manual（手动新建）/ ai（截图分析自动提取）
- ts: 创建时间 ISO

与时间线联动（增量法）：定时截屏是独立进程（任务计划 pythonw），为免两个进程
同时写 todos.json 造成覆盖竞争，todos.json 只由 GUI 进程写。GUI 每次打开待办页
或刷新时间线时调 sync_from_records()：按文件 mtime 找出上次同步后改动过的
jsonl，解析其中的 todo 字段，按"文本+日期"去重后 upsert 进待办列表。
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

import config

STATUSES = ("未开始", "进行中", "已完成", "归档")
PRIORITIES = ("高", "中", "低")
PRIORITY_ORDER = {p: i for i, p in enumerate(PRIORITIES)}

_logger = config.setup_logging()


def _empty() -> dict:
    return {"last_synced_ts": 0.0, "items": [], "deleted": []}


def load() -> dict:
    """读取 todos.json；文件缺失/损坏时返回空结构（不抛错，下次保存重建）。"""
    try:
        data = json.loads(config.TODOS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data.setdefault("deleted", [])  # 兼容旧文件（无墓碑字段）
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return _empty()


def save(data: dict) -> None:
    config.RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    config.TODOS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _changed_since(last_ts: float) -> list:
    """上次同步后改动过的 jsonl 文件（按 mtime，倒序）。"""
    if not config.RAW_DIR.exists():
        return []
    changed = []
    for p in config.RAW_DIR.glob("*.jsonl"):
        try:
            if p.stat().st_mtime > last_ts:
                changed.append(p)
        except OSError:
            continue
    return sorted(changed, key=lambda p: p.name)


def sync_from_records() -> dict:
    """增量扫描时间线，把分析提取的 todo 字段同步进待办列表，返回新增条数。

    去重键 = 文本（去首尾空白）+ 记录日期；已存在（含已归档）则跳过。
    同步完成后 last_synced_ts 推进到当前时刻，避免重复扫描。
    """
    data = load()
    items = data["items"]
    existing = {(it["text"].strip(), it["ts"][:10]) for it in items if it.get("source") == "ai"}
    # 墓碑：用户删除过的 AI 待办键不再同步回来（jsonl 原始记录仍在，会持续被扫描）
    existing.update((text, day) for text, day in data.get("deleted", []))
    added = 0
    for path in _changed_since(data.get("last_synced_ts", 0.0)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            _logger.warning("待办同步读取 %s 失败: %s", path.name, e)
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = str(rec.get("todo") or "").strip()
            if not text:
                continue
            day = rec.get("ts", "")[:10]
            if (text, day) in existing:
                continue
            existing.add((text, day))
            items.append({
                "id": uuid.uuid4().hex[:8],
                "text": text,
                "status": "未开始",
                "priority": "中",
                "source": "ai",
                "ts": rec.get("ts") or datetime.now().isoformat(timespec="seconds"),
            })
            added += 1
    if added:
        data["last_synced_ts"] = datetime.now().timestamp()
        save(data)
        _logger.info("待办同步：新增 %d 条（%s）", added, path.name if path else "")
    return {"ok": True, "added": added}


def add(text: str, priority: str = "中") -> dict:
    """手动新建一条待办。"""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "待办内容不能为空"}
    if priority not in PRIORITIES:
        priority = "中"
    data = load()
    data["items"].append({
        "id": uuid.uuid4().hex[:8],
        "text": text,
        "status": "未开始",
        "priority": priority,
        "source": "manual",
        "ts": datetime.now().isoformat(timespec="seconds"),
    })
    save(data)
    return {"ok": True, "item": data["items"][-1]}


def set_status(todo_id: str, status: str) -> dict:
    """切换待办状态（勾选完成 / 状态变更）。"""
    if status not in STATUSES:
        return {"ok": False, "error": f"状态必须是 {STATUSES} 之一"}
    data = load()
    for it in data["items"]:
        if it["id"] == todo_id:
            it["status"] = status
            save(data)
            return {"ok": True, "item": it}
    return {"ok": False, "error": "待办不存在"}


def remove(todo_id: str) -> dict:
    """删除一条待办；AI 来源的记入墓碑，防止下次同步时被 jsonl 重新捞回。"""
    data = load()
    for it in data["items"]:
        if it["id"] == todo_id:
            if it.get("source") == "ai":
                key = (it["text"].strip(), (it.get("ts") or "")[:10])
                deleted = data.setdefault("deleted", [])
                if key not in deleted:
                    deleted.append(key)
                if len(deleted) > 500:  # 墓碑上限，防止无限膨胀（超限丢最旧的）
                    del deleted[:len(deleted) - 500]
            data["items"].remove(it)
            save(data)
            return {"ok": True}
    return {"ok": False, "error": "待办不存在"}
