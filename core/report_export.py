"""将 dailylog 的 Markdown 报告转换为外发格式。"""
from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path


def email_text(markdown: str) -> str:
    """生成适合粘贴进邮件的纯文本，不保留 Markdown 标记。"""
    lines = []
    for raw_line in markdown.replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if re.match(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$", line):
            continue
        line = re.sub(r"^#{1,3}\s+", "", line)
        line = re.sub(r"^\s*[-*]\s+", "• ", line)
        line = re.sub(r"^\s*\d+[.)]\s+", lambda m: m.group(0).strip() + " ", line)
        line = line.strip("|").replace("|", " | ")
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"`(.+?)`", r"\1", line)
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def rich_html(markdown: str) -> str:
    """生成无外部资源的安全 HTML，供 Windows 富文本剪贴板使用。"""
    parts: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    table_rows: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            parts.append("<p>" + "<br>".join(_inline(item) for item in paragraph) + "</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_tag:
            parts.append(f"</{list_tag}>")
            list_tag = None

    def flush_table() -> None:
        if not table_rows:
            return
        header, *body = table_rows
        head_html = "".join(f"<th>{_inline(cell)}</th>" for cell in header)
        body_html = "".join(
            "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>"
            for row in body
        )
        parts.append(f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>")
        table_rows.clear()

    for raw_line in markdown.replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_table()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_table()
            level = len(heading.group(1))
            parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if _is_table_divider(line):
            continue
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            flush_paragraph()
            flush_list()
            table_rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
            continue
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if bullet or numbered:
            flush_paragraph()
            flush_table()
            next_tag = "ul" if bullet else "ol"
            if list_tag != next_tag:
                flush_list()
                parts.append(f"<{next_tag}>")
                list_tag = next_tag
            parts.append(f"<li>{_inline((bullet or numbered).group(1))}</li>")
            continue
        flush_list()
        flush_table()
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    flush_table()
    return "".join(parts)


def write_pdf(markdown: str, destination: Path) -> None:
    """生成干净的 A4 报告 PDF。"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError("缺少 PDF 导出依赖，请安装 requirements-extension.txt") from exc

    font_path = _system_font_path()
    if not font_path:
        raise RuntimeError("未找到可用的系统中文字体，无法导出 PDF")

    try:
        pdfmetrics.registerFont(TTFont("DailylogCjk", str(font_path), subfontIndex=0))
    except (OSError, TypeError) as exc:
        raise RuntimeError(f"系统中文字体无法加载：{font_path.name}") from exc

    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "DailylogBody",
        parent=styles["BodyText"],
        fontName="DailylogCjk",
        fontSize=10.5,
        leading=17,
        alignment=TA_LEFT,
        spaceAfter=7,
    )
    headings = {
        1: ParagraphStyle("DailylogH1", parent=base, fontSize=18, leading=25, spaceBefore=8, spaceAfter=12),
        2: ParagraphStyle("DailylogH2", parent=base, fontSize=14, leading=21, spaceBefore=12, spaceAfter=8),
        3: ParagraphStyle("DailylogH3", parent=base, fontSize=11.5, leading=18, spaceBefore=9, spaceAfter=5),
    }
    story = []
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        if not table_rows:
            return
        width = 170 * mm / max(len(table_rows[0]), 1)
        table = Table(table_rows, colWidths=[width] * len(table_rows[0]), repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "DailylogCjk"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("LEADING", (0, 0), (-1, -1), 14),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4EEF1")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#DCCED4")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([table, Spacer(1, 7)])
        table_rows.clear()

    for raw_line in markdown.replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            flush_table()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_table()
            story.append(Paragraph(_pdf_text(heading.group(2)), headings[len(heading.group(1))]))
            continue
        if _is_table_divider(line):
            continue
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            table_rows.append([_pdf_text(cell.strip()) for cell in line.strip().strip("|").split("|")])
            continue
        flush_table()
        text = re.sub(r"^\s*[-*]\s+", "• ", line)
        story.append(Paragraph(_pdf_text(text), base))

    flush_table()
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="dailylog 报告",
    )
    document.build(story)


def _inline(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)


def _pdf_text(value: str) -> str:
    # 系统中文字体不一定含有 emoji 等符号字形。PDF 无法可靠回退字体时，
    # 跳过这些图案，避免输出缺字方块或乱码。
    safe_value = "".join(
        character
        for character in value
        if unicodedata.category(character) != "So"
        and character not in {"\u200d", "\ufe0e", "\ufe0f"}
    )
    escaped = html.escape(safe_value)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return re.sub(r"`(.+?)`", r"<font color='#555555'>\1</font>", escaped)


def _is_table_divider(value: str) -> bool:
    return bool(re.match(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$", value))


def _system_font_path() -> Path | None:
    fonts = Path(r"C:\Windows\Fonts")
    for name in ("msyh.ttc", "msyhbd.ttc", "simsun.ttc", "simhei.ttf"):
        path = fonts / name
        if path.exists():
            return path
    return None
