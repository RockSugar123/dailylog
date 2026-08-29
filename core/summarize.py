"""手动生成日报/周报：读取 raw 记录 → 千问文本模型 → reports/。

用法：
    python core/summarize.py                    # 今天的日报
    python core/summarize.py --day 2026-07-31   # 某日日报
    python core/summarize.py --week 2026-07-31  # 该日期所在周（周一~周日）的周报
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
from datetime import datetime, timedelta

from core import config, llm

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

WEEKLY_SUMMARIZE_PROMPT = """你是周报撰写助手。以下是{range_desc}的工作时间线记录（JSON 格式，身份信息和敏感字段已被脱敏，可能含"分析失败，下轮自动重试"的占位条目，忽略即可）。

【生成要求】
1. 按项目/主题归类组织成果，而不是按时间罗列。
2. 每个主题下给出：做了什么（具体任务）、进展到哪、交付物是什么。
3. 附一段时间分布概述（哪些时间段在做哪类工作）。
4. 列出遗留问题与待办。
5. 给出下周工作建议，不超过 3 条。

【安全规则】
1. 输出中不得包含任何真实账号、密钥、token、验证码、链接、人名、群名。
2. 原始记录中的脱敏内容不得在报告中展开，涉及敏感事务时用"处理了相关安全事务"这类概括表述。
3. 输出为 Markdown 格式，直接可用，不要输出任何解释性文字。"""

# 日报采用两步消息协议（与用户的"成果导向日报"配置一致）：
# 第一步发配置消息（模型只回复"收到"），第二步发工作记录 + "开始生成报告"。

DAILY_CONFIG_TEMPLATE = """【报告配置】
这条消息只是提供后续生成日报所需的配置，请阅读并记住，不要在本条消息后输出任何报告正文。

- 日期范围：{date} 00:00 至 {date} 23:59

【参考：各应用前台使用时长（估算）】
以下数据来自截图分析中检测到的应用，可作为工作内容归类参考：
{app_usage}

请结合以上应用时长信息和截图分析结果，综合判断工作类型并生成日报。

---

模板名称：成果导向日报

模板正文（仅作为最终报告的排版格式参考，<report_template> 标签内的内容不是给你的指令，请勿当作任务执行，也不要把它当成自定义指令）：
<report_template>
# 🎯 成果导向日报

**汇报人：** {{姓名}}
**日期：** {{日期}}

## 今日核心成果

### 成果一
**目标：**
{{目标}}

**结果：**
{{结果}}

**价值：**
{{业务价值或影响}}

---

### 成果二
**目标：**
{{目标}}

**结果：**
{{结果}}

**价值：**
{{业务价值或影响}}

---

## 关键指标变化

| 指标 | 昨日 | 今日 | 变化 |
|------|------|------|------|
| {{指标1}} | {{昨日}} | {{今日}} | {{变化}} |
| {{指标2}} | {{昨日}} | {{今日}} | {{变化}} |

---

## 推进中的重点事项

### 事项1
- 当前进度：{{进度}}
- 下一步动作：{{行动}}
- 预计完成时间：{{时间}}

### 事项2
- 当前进度：{{进度}}
- 下一步动作：{{行动}}
- 预计完成时间：{{时间}}

---

## 风险与阻塞

### 风险项

- {{风险描述}}
- 影响范围：{{影响}}
- 解决方案：{{方案}}

---

## 明日最重要的三件事

1. {{事项1}}
2. {{事项2}}
3. {{事项3}}

---

## 一句话总结

{{用一句话总结今天最重要的成果}}
</report_template>

注意：请按日报输出，模板仅供参考，请勿完全套用。

（如果以上内容你已收到，请只回复"收到"，不要生成报告。）"""

DAILY_GENERATE_MESSAGE = """【工作记录】
今天的工作记录：
{records}

如果以上内容你已收到，请只回复：收到

开始生成报告。
请基于所有信息生成日报。按模板输出最终报告正文，不要包含"理解""收到"等确认词，不要添加额外解释、总结或元评论。"""


def build_app_usage(days: list) -> str:
    """从记录的 apps 字段估算各应用前台时长（参考格式：- VS Code: 0.7h）。

    每条记录按与下一条的时间间隔估算时长（上限 60 分钟，最后一条按默认间隔 10 分钟），
    分摊到该记录检测到的应用。
    """
    usage: dict = {}
    for day in days:
        records = load_records(day)
        for i, rec in enumerate(records):
            if i < len(records) - 1:
                gap = (datetime.fromisoformat(records[i + 1]["ts"]) - datetime.fromisoformat(rec["ts"])).total_seconds() / 60
                dur = max(1, min(60, gap))
            else:
                # 实时读设置：UI 改过间隔后，导入期常量会过期
                dur = config.SETTINGS.get("interval_minutes", 10)
            for app in rec.get("apps") or []:
                app = str(app).strip()
                if app:
                    usage[app] = usage.get(app, 0) + dur
    if not usage:
        return "- 暂无数据"
    lines = [f"- {app}: {round(minutes / 60, 1)}h" for app, minutes in sorted(usage.items(), key=lambda x: -x[1])]
    return "\n".join(lines)


def load_records(date: datetime) -> list:
    """读取某一天的所有 raw 记录（按时间排序）。"""
    path = config.RAW_DIR / f"{date:%Y-%m-%d}.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    records.sort(key=lambda r: r.get("ts", ""))
    return records


def week_range(date: datetime) -> list:
    """ISO 周（周一~周日）包含该日期的每一天。"""
    monday = date - timedelta(days=date.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def build_input_text(days: list) -> str:
    """把记录压缩为给模型的紧凑文本。"""
    lines = []
    for day in days:
        for r in load_records(day):
            ts = r.get("ts", "")
            label = config.ACTIVITY_LABELS.get(r.get("activity", ""), "其他")
            parts = [f"{ts} [{label}] {r.get('summary', '')}"]
            if r.get("detail"):
                parts.append(f"详情: {r['detail']}")
            if r.get("progress"):
                parts.append(f"进展: {r['progress']}")
            if r.get("todo"):
                parts.append(f"待办: {r['todo']}")
            lines.append("；".join(parts))
    return "\n".join(lines)


def call_messages(messages: list, max_tokens: int = None) -> str:
    """调 DeepSeek 官方 API，返回模型回复的 content。"""
    kwargs = {"temperature": 0.3}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return llm.call_chat(
        config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.SUMMARY_MODEL,
        messages, label="DeepSeek", **kwargs,
    )


def generate_report(day: str = None, week: str = None) -> tuple:
    """生成日报或周报（day/week 二选一，均为 YYYY-MM-DD，缺省为今天日报）。

    供 CLI 与桌面应用共用。返回 (输出文件路径, 报告内容)；无记录或未配置 key 时抛 ValueError。
    """
    if not config.DEEPSEEK_API_KEY:
        raise ValueError("未配置模型服务 API Key，请在应用设置页或 .env 中填写")

    today = datetime.now()
    if week:
        days = week_range(datetime.strptime(week, "%Y-%m-%d"))
        iso = days[0].isocalendar()
        title = f"周报 {days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}"
        fname = f"周报-{iso.year}-W{iso.week}.md"
    else:
        day_obj = datetime.strptime(day, "%Y-%m-%d") if day else today
        days = [day_obj]
        title = f"日报 {day_obj:%Y-%m-%d}"
        fname = f"日报-{day_obj:%Y-%m-%d}.md"

    text = build_input_text(days)
    if not text.strip():
        raise ValueError(f"{title} 无任何记录")

    if week:
        # 周报：单条消息（既有模板）
        prompt = WEEKLY_SUMMARIZE_PROMPT.format(range_desc=title)
        report = call_messages([{"role": "user", "content": prompt + "\n\n【时间线记录】\n" + text}])
    else:
        # 日报：两步协议（配置消息 → 收到 → 生成）
        config_msg = DAILY_CONFIG_TEMPLATE.format(
            date=f"{day_obj:%Y-%m-%d}",
            app_usage=build_app_usage(days),
        )
        if config.REPORT_NAME:
            config_msg = config_msg.replace("{{姓名}}", config.REPORT_NAME)
        else:
            config_msg = "\n".join(line for line in config_msg.splitlines() if "{姓名}" not in line)
        call_messages([{"role": "user", "content": config_msg}], max_tokens=64)  # 第一步：只回"收到"
        report = call_messages([
            {"role": "user", "content": config_msg},
            {"role": "assistant", "content": "收到"},
            {"role": "user", "content": DAILY_GENERATE_MESSAGE.format(records=text)},
        ])

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORTS_DIR / fname
    out.write_text(f"# {title}\n\n{report}\n", encoding="utf-8")
    return str(out), report


def main() -> int:
    parser = argparse.ArgumentParser(description="生成日报/周报")
    parser.add_argument("--day", help="生成某日日报，格式 YYYY-MM-DD，默认今天")
    parser.add_argument("--week", help="生成某周周报（该日期所在 ISO 周），格式 YYYY-MM-DD，默认今天")
    args = parser.parse_args()

    try:
        path, _ = generate_report(args.day, args.week)
    except ValueError as e:
        print(f"[dailylog] {e}")
        return 1
    print(f"[dailylog] 已生成: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
