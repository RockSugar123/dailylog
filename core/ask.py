"""历史日志问答：检索相关片段（core/indexer）→ 总结模型组织回答（附引用）。

问答模型复用「报告总结」端点配置（DEEPSEEK_* 别名），不单独引入一套模型配置。
支持会话（core/sessions）：同一会话内追问时带最近几轮上下文，检索词先由模型
改写成独立完整的问题再检索；首轮回答落盘后可由 maybe_generate_title 提炼标题。
用法：
    python core/ask.py "上个月我都在忙什么"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, indexer, llm, sessions

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

ASK_PROMPT = """你是 dailylog 的工作日志问答助手。根据下面检索到的历史记录片段回答用户问题。

【规则】
1. 只依据片段内容回答，不要编造；片段不足以回答时，明确说明"记录里没有找到相关内容"。
2. 在依据某片段的关键句后标注来源编号，格式如 [1][2]，编号对应片段序号。
3. 涉及多天/多次记录时按主题归纳，不要逐条罗列流水账。
4. 用简洁的中文直接给结论。

【检索片段】
{context}

【用户问题】
{question}"""

REWRITE_PROMPT = """你是检索查询改写器。根据对话历史，把用户的最新问题改写成不依赖上下文、
可独立用于检索的完整查询（把「那/它/昨天」等指代词和时间词换成具体内容或日期）。

【对话历史】
{history}

【最新问题】
{question}

只输出改写后的查询，不要任何解释或引号。"""

TITLE_PROMPT = """根据下面这次问答，提炼一个不超过{max_chars}个字的会话标题，概括话题即可。

【用户问题】
{question}

【回答】
{answer}

只输出标题本身，不要引号和句末标点。"""


def build_context(hits: list) -> str:
    """把检索结果拼成带编号的上下文文本，编号与引用列表一一对应。"""
    lines = []
    for i, h in enumerate(hits, 1):
        where = " ".join(p for p in (h["date"], h["time"]) if p)
        lines.append(f"[{i}] {where} · {h['heading']}\n{h['text']}")
    return "\n\n".join(lines)


def _validate(question: str) -> None:
    """公共校验：问题非空 + 总结端点配置完整，不通过抛 ValueError。"""
    if not question:
        raise ValueError("问题不能为空")
    if not config.DEEPSEEK_API_KEY:
        raise ValueError("未配置模型服务 API Key，请先在设置页「模型服务」中填写")
    if not config.DEEPSEEK_BASE_URL or not config.SUMMARY_MODEL:
        raise ValueError("总结模型未配置完整（接口地址/模型名称），请在设置页「模型服务」中填写")


def _prepare(question: str) -> tuple:
    """校验 + 懒同步索引 + 检索。返回 (prompt, hits, stats)；无可检索内容时 prompt 为 None。"""
    stats = indexer.sync_index()
    if not stats.get("chunks"):
        return None, [], stats
    hits = indexer.search(question, config.ASK_TOP_K)
    if not hits:
        return None, [], stats
    return ASK_PROMPT.format(context=build_context(hits), question=question), hits, stats


def _citations(hits: list) -> list:
    return [
        {"idx": i, "source": h["source"], "date": h["date"], "time": h["time"],
         "heading": h["heading"], "name": Path(h["file_path"]).name, "score": h["score"]}
        for i, h in enumerate(hits, 1)
    ]


def _empty_answer(stats: dict) -> dict:
    if not stats.get("chunks"):
        answer = "记录里还没有可检索的内容。先让 dailylog 记录一段时间，再来问吧。"
    else:
        answer = "记录里没有找到相关内容。可以换个说法再问一次。"
    return {"answer": answer, "citations": [], "stats": stats}


def _history_text(history: list, width: int = 300) -> str:
    """把 messages 历史压成改写 prompt 用的纯文本，每条截断防 prompt 膨胀。"""
    lines = []
    for m in history:
        who = "用户" if m["role"] == "user" else "助手"
        lines.append(f"{who}：{(m['content'] or '')[:width]}")
    return "\n".join(lines)


def rewrite_query(question: str, history: list) -> str:
    """结合会话上文把追问改写成独立检索词；网络/服务错误抛 RuntimeError（调用方回退原文）。"""
    out = llm.call_chat(
        config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.SUMMARY_MODEL,
        [{"role": "user", "content": REWRITE_PROMPT.format(
            history=_history_text(history), question=question)}],
        label="检索改写", temperature=0,
    )
    return out.strip().strip('"“”「」') or question


def generate_title(question: str, answer: str) -> str:
    """由首轮问答提炼会话标题；网络/服务错误抛 RuntimeError（调用方保留临时标题）。"""
    out = llm.call_chat(
        config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.SUMMARY_MODEL,
        [{"role": "user", "content": TITLE_PROMPT.format(
            max_chars=config.ASK_TITLE_MAX_CHARS,
            question=question[:300], answer=answer[:600])}],
        label="会话起名", temperature=0.3,
    )
    title = out.strip().splitlines()[0].strip().strip('"“”「」')
    return title[: config.ASK_TITLE_MAX_CHARS]


def maybe_generate_title(session_id: str) -> str | None:
    """首轮问答落盘后自动提炼标题；manual 已改名 / 非首轮 / 失败时不动，返回新标题或 None。"""
    sess = sessions.load(session_id)
    if not sess or sess.get("title_source") != "temp":
        return None
    msgs = sess.get("messages", [])
    if len(msgs) < 2 or msgs[0].get("role") != "user" or msgs[1].get("role") != "assistant":
        return None  # 只在首轮（会话第一条问答）后起名
    try:
        title = generate_title(msgs[0]["content"], msgs[1]["content"])
    except Exception as e:  # noqa: BLE001 起名失败不影响问答，保留临时标题
        config.setup_logging().warning("会话起名失败（保留临时标题）: %s", e)
        return None
    if not title:
        return None
    sess = sessions.set_ai_title(session_id, title)
    return sess["title"] if sess else None


def _run(question: str, session_id, on_delta) -> dict:
    """问答主流程：载入会话历史 → 改写检索词 → 检索 → 生成 → 落盘。on_delta 为 None 时一次性返回。

    session_id: 会话 id 续写已有会话；空串开新会话；None 只问答不落盘（CLI 场景）。
    """
    question = (question or "").strip()
    _validate(question)

    history = []
    if session_id:
        sess = sessions.load(session_id)
        if sess:
            history = sessions.recent_history(sess, config.ASK_ANSWER_TURNS)

    search_term = question
    if history:
        try:
            search_term = rewrite_query(question, history)
        except Exception as e:  # noqa: BLE001 改写失败回退原始问题，不阻断问答
            config.setup_logging().warning("检索词改写失败，按原问题检索: %s", e)

    prompt, hits, stats = _prepare(search_term)
    if prompt is None:
        answer, citations = _empty_answer(stats)["answer"], []
    else:
        messages = history + [{"role": "user", "content": prompt}]
        if on_delta is None:
            answer = llm.call_chat(
                config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.SUMMARY_MODEL,
                messages, label="问答", temperature=0.3,
            )
        else:
            answer = llm.call_chat_stream(
                config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.SUMMARY_MODEL,
                messages, label="问答", on_delta=on_delta, temperature=0.3,
            )
        citations = _citations(hits)

    if session_id is None:
        return {"answer": answer, "citations": citations, "stats": stats}
    sess = sessions.append_exchange(session_id, question, answer, citations)
    return {"answer": answer, "citations": citations, "stats": stats,
            "session_id": sess["id"], "title": sess["title"],
            "title_source": sess["title_source"]}


def ask(question: str, session_id=None) -> dict:
    """执行一次问答（一次性返回）；配置缺失抛 ValueError，网络/服务错误抛 RuntimeError。

    session_id 传 None 不落盘（CLI 场景）；空串/会话 id 按会话存档处理。
    """
    return _run(question, session_id, on_delta=None)


def ask_stream(question: str, session_id: str, on_delta) -> dict:
    """流式问答：on_delta(text) 逐段回调增量文本（供 UI 逐字渲染），返回完整结果。

    会话逻辑与 ask() 相同；无可检索内容时把提示语整段回调一次。
    """
    return _run(question, session_id, on_delta=on_delta)


def main() -> int:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print("用法：python core/ask.py \"你的问题\"")
        return 1
    try:
        result = ask(question)
    except (ValueError, RuntimeError) as e:
        print(f"[dailylog] {e}")
        return 1
    print(result["answer"])
    if result["citations"]:
        print("\n—— 来源 ——")
        for c in result["citations"]:
            where = " ".join(p for p in (c["date"], c["time"]) if p) or c["name"]
            print(f"[{c['idx']}] {where} · {c['heading']}（{c['name']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
