"""调用当前配置的视觉模型分析截图（OpenAI 兼容端点），返回结构化记录。"""
import base64
import io
import json
import re
from pathlib import Path

from PIL import Image

from core import config, llm

ANALYZE_PROMPT = """你是工作日志记录助手。分析这张屏幕截图，记录此刻正在进行的工作活动。

【核心原则】
1. 尽可能记录有日报价值的工作内容：工作主题、任务名称、项目方向、需求内容、技术问题、交付物、进展、待办。
2. 保护隐私：不记录私人聊天细节、联系人身份、账号、密钥、完整链接等敏感信息。
3. 隐私保护不等于空泛描述：只脱敏"身份信息"和"敏感字段"，工作任务本身尽量保留细节。

【你应该记录什么】
1. 当前正在做的具体工作任务。
2. 当前正在阅读、编辑、核对、调试、整理、沟通的内容主题。
3. 任务所属工作方向，如：产品设计、代码开发、运营分析、数据复盘、客户支持、项目管理、日报整理、资料研究等。
4. 能用于日报的具体进展、待办、交付物。
5. 若在聊天工具里处理工作，提取"工作事项"和"任务含义"，不复述原文。

【你不应该记录什么】
1. 桌面壁纸、系统状态栏、时间、电量、天气、Dock、任务栏等无关信息。
2. 联系人昵称、群名、备注名、头像文字、账号名。
3. 聊天消息逐字内容、私人聊天细节。
4. 手机号、邮箱、身份证、银行卡、地址、验证码、密码、Token、API Key、Cookie。
5. 客户个人身份、员工个人身份、具体薪酬绩效、敏感财务明细。

【沟通界面处理（微信/飞书/钉钉/Slack/邮件/私信/群聊等）】
允许输出：沟通的工作主题、任务方向、可识别的工作需求/待办/结论/进展、文件或链接的大致用途、正在处理这些沟通的行为。
禁止输出：联系人是谁、群名、对方原话、逐字内容、完整链接、账号、手机号、邮箱、订单号、密钥。
示例："做海龟策略回测" → 输出"正在处理量化交易策略回测相关任务"。
私人闲聊 → 只输出"当前包含私人沟通内容，已脱敏，不纳入日报"。

【输出要求】
1. 只输出一个 JSON 对象，不要输出任何其他文字、注释或 markdown 代码块标记。
2. 截图无工作内容（纯私人界面、壁纸、无活动）时 summary 输出"无工作活动"。
3. 不要编造截图中不存在的内容。
4. 隐私与工作记录冲突时，优先保留"脱敏后的工作事项"。

{
  "activity": "coding|writing|meeting|research|communication|data|support|browsing|idle|other",
  "summary": "不超过40字的中文工作摘要",
  "detail": "任务名称/主题/项目方向，保留工作细节，脱敏身份",
  "progress": "进展或交付物，没有则为空字符串",
  "todo": "识别到的待办，没有则为空字符串",
  "apps": ["检测到的应用/网站"],
  "contains_sensitive": true
}"""

REQUIRED_FIELDS = ("activity", "summary", "detail", "progress", "todo", "apps", "contains_sensitive")


def encode_image(png_path: Path) -> str:
    """截图 → 缩放 JPEG → base64 data URL。

    部分模型服务限制请求体大小，4K 屏的原始 PNG base64 后动辄超限（HTTP 400
    "Request payload is too large"），必须先缩放并转 JPEG 压缩。
    """
    img = Image.open(png_path).convert("RGB")
    if max(img.size) > config.ANALYZE_IMAGE_MAX_SIDE:
        img.thumbnail((config.ANALYZE_IMAGE_MAX_SIDE, config.ANALYZE_IMAGE_MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=config.ANALYZE_JPEG_QUALITY)
    data = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{data}"


def parse_json(content: str) -> dict:
    """宽容解析模型输出：整体解析失败则提取首个 {...} 块。"""
    content = content.strip()
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ValueError(f"模型输出无法解析为 JSON: {content[:200]}")
        result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError(f"模型输出不是 JSON 对象: {content[:200]}")
    return result


def normalize(result: dict) -> dict:
    """校验并补齐必填字段，未知 activity 归为 other。"""
    result = {k: result.get(k, [] if k == "apps" else "") for k in REQUIRED_FIELDS}
    result["activity"] = result["activity"] if result["activity"] in config.ACTIVITY_LABELS else "other"
    for k in ("summary", "detail", "progress", "todo"):
        if not isinstance(result[k], str):
            result[k] = ""
    if not isinstance(result["apps"], list):
        result["apps"] = []
    return result


def call_analyze(image_url: str, existing_todos: list = None, foreground: str = "") -> dict:
    """调当前配置的视觉模型分析截图，返回规范化 dict；失败抛异常。

    existing_todos：当日已提取的待办列表，随请求带给模型做去重，
    避免同一件事被反复生成待办（碎片化）。
    foreground："进程名 / 窗口标题" 形式的前台窗口元数据，作画面消歧的硬信号
    （如 code.exe=VS Code），不落盘；为空时不附加。
    """
    prompt = ANALYZE_PROMPT
    if foreground:
        prompt += (
            f"\n\n【当前前台窗口】{foreground}\n"
            "以此为第一优先依据判断 activity 分类与 apps 字段（进程名是可靠信号，"
            "如 code.exe 是 VS Code）；窗口标题仅作参考，禁止复述其中的联系人、"
            "账号、密钥等敏感信息。"
        )
    if existing_todos:
        prompt += (
            "\n\n【今日已记录的待办】\n"
            + "\n".join(f"- {t}" for t in existing_todos)
            + "\n以上待办已存在。若当前屏幕内容与其中某条重复、或只是进展描述，"
              "todo 字段输出空字符串，不要重复生成。"
        )
    content = llm.call_chat(
        config.ANALYZE_BASE_URL, config.ANALYZE_API_KEY, config.ANALYZE_MODEL,
        [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": prompt},
            ],
        }],
        label="截图分析",
        temperature=config.ANALYZE_TEMPERATURE,
        top_p=config.ANALYZE_TOP_P,
        max_tokens=config.ANALYZE_MAX_TOKENS,
        stream=False,
        thinking={"type": "enabled" if config.ANALYZE_THINKING else "disabled"},
    )
    return normalize(parse_json(content))
