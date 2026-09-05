"""问答会话存档：data/sessions/ 每会话一个 JSON 文件（历史会话功能）。

文件结构：{id, title, title_source, created_at, updated_at, messages}
- title_source: temp（首问截断的临时标题）/ ai（首轮后模型提炼）/ manual（用户手动改名）
- 命名规则：首轮回答落盘后由模型提炼一次；title_source 为 manual 后永不被覆盖
- messages 每条：{role: "user"|"assistant", content, ts}，assistant 另带 citations
- 只有完整的一问一答才落盘（生成失败不存，避免孤立提问堆积）

并发：问答写入在 app.py 的后台线程，改名/删除在 JS 桥线程，
统一用模块级锁串行化读改写；个人量级（百级会话）无需更细粒度。
"""
import json
import os
import threading
import uuid
from datetime import datetime

from core import config

_logger = config.setup_logging()

_LOCK = threading.Lock()

MANUAL_TITLE_MAX = 50  # 手动重命名的长度上限（AI 提炼用 config.ASK_TITLE_MAX_CHARS）


def _now() -> str:
    # 带微秒：同秒内创建的会话也能按时间精确排序（前端展示时截到秒）
    return datetime.now().isoformat()


def _path(sid: str):
    return config.SESSIONS_DIR / f"{sid}.json"


def _write(sess: dict) -> None:
    """原子写：先写 .tmp 再替换，避免写一半崩溃留损坏文件。"""
    config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(sess["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_unlocked(sid: str) -> dict | None:
    """读单个会话；文件缺失/损坏返回 None（损坏时落日志，列表会跳过）。"""
    try:
        data = json.loads(_path(sid).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as e:
        _logger.error("会话文件损坏 %s: %s", sid, e)
    return None


def load(sid: str) -> dict | None:
    if not sid:
        return None
    with _LOCK:
        return _load_unlocked(sid)


def list_sessions() -> list:
    """全部会话摘要（更新时间倒序，供浮层「历史」列表）。"""
    with _LOCK:
        items = []
        if config.SESSIONS_DIR.exists():
            for p in config.SESSIONS_DIR.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as e:
                    _logger.error("跳过无法解析的会话文件 %s: %s", p.name, e)
                    continue
                if isinstance(data, dict) and data.get("id"):
                    items.append({
                        "id": data["id"],
                        "title": data.get("title", ""),
                        "updated_at": data.get("updated_at", ""),
                        "turns": sum(1 for m in data.get("messages", [])
                                     if m.get("role") == "user"),
                    })
    items.sort(key=lambda it: it["updated_at"], reverse=True)
    return items


def append_exchange(sid: str, question: str, answer: str, citations: list) -> dict:
    """落盘一问一答；sid 为空或文件不存在时新建会话（临时标题取首问前 20 字）。"""
    with _LOCK:
        sess = _load_unlocked(sid) if sid else None
        if sess is None:
            sess = {
                "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
                "title": question.strip()[:20] or "新的问答",
                "title_source": "temp",
                "created_at": _now(),
                "updated_at": _now(),
                "messages": [],
            }
        sess["messages"].append({"role": "user", "content": question, "ts": _now()})
        sess["messages"].append({"role": "assistant", "content": answer,
                                 "citations": citations, "ts": _now()})
        sess["updated_at"] = _now()
        _write(sess)
        return sess


def set_ai_title(sid: str, title: str) -> dict | None:
    """写入 AI 提炼的标题；用户已手动改名（manual）时不覆盖。"""
    with _LOCK:
        sess = _load_unlocked(sid)
        if sess is None or sess.get("title_source") == "manual":
            return sess
        sess["title"] = title
        sess["title_source"] = "ai"
        _write(sess)
        return sess


def rename(sid: str, title: str) -> dict | None:
    """手动重命名（title_source 置 manual，此后 AI 起名不再覆盖）。"""
    title = title.strip()[:MANUAL_TITLE_MAX]
    if not title:
        return None
    with _LOCK:
        sess = _load_unlocked(sid)
        if sess is None:
            return None
        sess["title"] = title
        sess["title_source"] = "manual"
        _write(sess)
        return sess


def delete(sid: str) -> bool:
    try:
        with _LOCK:
            _path(sid).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as e:  # Windows 下文件被占用等
        _logger.error("删除会话失败 %s: %s", sid, e)
        return False


def recent_history(sess: dict, turns: int) -> list:
    """最近 N 轮完整问答对，转 OpenAI messages 格式（供多轮 prompt / 检索词改写）。

    只取有成对回答的提问——末尾未获回答的孤立提问（理论上不该出现）不进上下文，
    避免部分供应商对连续同角色消息报错。
    """
    pairs = []
    msgs = sess.get("messages", [])
    i = 0
    while i < len(msgs):
        if (msgs[i].get("role") == "user" and i + 1 < len(msgs)
                and msgs[i + 1].get("role") == "assistant"):
            pairs.append((msgs[i]["content"], msgs[i + 1]["content"]))
            i += 2
        else:
            i += 1
    out = []
    for q, a in pairs[max(0, len(pairs) - turns):]:
        out.append({"role": "user", "content": q})
        out.append({"role": "assistant", "content": a})
    return out
