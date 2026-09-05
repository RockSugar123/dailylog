"""历史日志问答：检索相关片段（core/indexer）→ 总结模型组织回答（附引用）。

问答模型复用「报告总结」端点配置（DEEPSEEK_* 别名），不单独引入一套模型配置。
用法：
    python core/ask.py "上个月我都在忙什么"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, indexer, llm

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


def build_context(hits: list) -> str:
    """把检索结果拼成带编号的上下文文本，编号与引用列表一一对应。"""
    lines = []
    for i, h in enumerate(hits, 1):
        where = " ".join(p for p in (h["date"], h["time"]) if p)
        lines.append(f"[{i}] {where} · {h['heading']}\n{h['text']}")
    return "\n\n".join(lines)


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


def ask(question: str) -> dict:
    """执行一次问答（一次性返回）；配置缺失抛 ValueError，网络/服务错误抛 RuntimeError。"""
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")
    if not config.DEEPSEEK_API_KEY:
        raise ValueError("未配置模型服务 API Key，请先在设置页「模型服务」中填写")
    if not config.DEEPSEEK_BASE_URL or not config.SUMMARY_MODEL:
        raise ValueError("总结模型未配置完整（接口地址/模型名称），请在设置页「模型服务」中填写")

    prompt, hits, stats = _prepare(question)
    if prompt is None:
        return _empty_answer(stats)

    answer = llm.call_chat(
        config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.SUMMARY_MODEL,
        [{"role": "user", "content": prompt}], label="问答", temperature=0.3,
    )
    return {"answer": answer, "citations": _citations(hits), "stats": stats}


def ask_stream(question: str, on_delta) -> dict:
    """流式问答：on_delta(text) 逐段回调增量文本（供 UI 逐字渲染），返回完整结果。

    校验与检索与 ask() 相同；无可检索内容时把提示语整段回调一次。
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")
    if not config.DEEPSEEK_API_KEY:
        raise ValueError("未配置模型服务 API Key，请先在设置页「模型服务」中填写")
    if not config.DEEPSEEK_BASE_URL or not config.SUMMARY_MODEL:
        raise ValueError("总结模型未配置完整（接口地址/模型名称），请在设置页「模型服务」中填写")

    prompt, hits, stats = _prepare(question)
    if prompt is None:
        result = _empty_answer(stats)
        on_delta(result["answer"])
        return result

    answer = llm.call_chat_stream(
        config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.SUMMARY_MODEL,
        [{"role": "user", "content": prompt}], label="问答", on_delta=on_delta,
        temperature=0.3,
    )
    return {"answer": answer, "citations": _citations(hits), "stats": stats}


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
