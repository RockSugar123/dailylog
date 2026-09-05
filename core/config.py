"""dailylog 所有可调参数集中在此。"""
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

# BASE_DIR = 源码根（开发期）或 exe 所在目录（打包后），用于定位代码/脚本；
# DATA_DIR = 运行数据（记录/报告/设置/密钥/日志），统一是 BASE_DIR 下的 data/ 子目录，
# 与代码文件分离：构建重建部署目录时 robocopy 排除 data/ 即可保住全部数据
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(DATA_DIR / ".env")


def load_settings() -> dict:
    """读取运行时设置（settings.json，UI 可修改；缺省用代码里的默认值）。"""
    try:
        return json.loads((DATA_DIR / "settings.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


SETTINGS = load_settings()
REPORT_NAME = SETTINGS.get("report_name", "")   # 日报"汇报人"，留空则不输出该行


def setup_logging() -> logging.Logger:
    """应用统一日志：dailylog.log，1MB 轮转保留 3 份（最多约 4MB），各模块共用。"""
    logger = logging.getLogger("dailylog")
    if logger.handlers:  # 幂等，避免重复挂 handler
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        DATA_DIR / "dailylog.log",
        maxBytes=1_000_000, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger

# 模型服务预设：官方 OpenAI 兼容端点，均支持多模态（截图分析需要视觉能力）。
# 设置页选供应商后用户只填模型名称 + Key；custom 时接口地址也由用户填。
# base_url 以代码为准（用户改不了官方端点），settings.json 只存 provider/model（和 custom 的地址）。
MODEL_PRESETS = {
    "dashscope": {
        "label": "阿里云百炼 · 通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3.5-omni-plus-2026-03-15",
        "hint": "在阿里云百炼（bailian.console.aliyun.com）获取 API Key",
    },
    "zhipu": {
        "label": "智谱开放平台 · GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5.3-flash",
        "hint": "在智谱开放平台（open.bigmodel.cn）获取 API Key",
    },
    "openai": {
        "label": "OpenAI · GPT",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5-mini",
        "hint": "在 OpenAI 平台（platform.openai.com）获取 API Key",
    },
    "moonshot": {
        "label": "月之暗面 · Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k3",
        "hint": "在 Moonshot 开放平台（platform.kimi.com）获取 API Key",
    },
    "siliconflow": {
        "label": "硅基流动 · SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "Qwen/Qwen3-VL-32B",
        "hint": "在硅基流动（cloud.siliconflow.cn）获取 API Key",
    },
    "doubao": {
        "label": "火山方舟 · 豆包",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-seed-1-6-vision-250815",
        "hint": "在火山方舟控制台（console.volcengine.com/ark）获取 API Key；模型填官方模型名或推理接入点 ID",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash-vision-exp",
        "hint": "在 DeepSeek 开放平台（platform.deepseek.com）获取 API Key",
    },
    "custom": {
        "label": "自定义（双模型）",
        "base_url": "",
        "default_model": "",
        "hint": "分别配置「截图分析」与「报告总结」的接口地址、模型名称与 Key",
    },
}

# 每供应商一份模型服务配置（settings.json 的 model_services：{pid: {model, base_url?}}），
# Key 按供应商存 .env 的 MODEL_KEY_<PID>。当前生效供应商 = model_provider
MODEL_SERVICES = SETTINGS.get("model_services")
if not isinstance(MODEL_SERVICES, dict):
    MODEL_SERVICES = {}

# 自定义模式下「报告总结」一份服务配置（settings.json 的 summary_services：{pid: {...}}），
# 与 model_services 一样由设置页保存；自定义就是完全手填，不留任何模型预置
SUMMARY_SERVICES = SETTINGS.get("summary_services")
if not isinstance(SUMMARY_SERVICES, dict):
    SUMMARY_SERVICES = {}


def model_key_for(provider: str) -> str:
    """某供应商已保存的 API Key：.env 的 MODEL_KEY_<PROVIDER>，旧键按归属回退。

    旧键只认归属供应商：ANALYZE_API_KEY / 旧统一键 MODEL_API_KEY 属千问，
    DEEPSEEK_API_KEY 属 DeepSeek；其余供应商没配过就是空，不串用别家的 Key。
    """
    legacy = {
        "dashscope": os.getenv("ANALYZE_API_KEY", "") or os.getenv("MODEL_API_KEY", ""),
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
        "custom": os.getenv("ANALYZE_API_KEY", ""),  # 自定义分析端点：旧版统一截图分析键
    }
    return (
        os.getenv(f"MODEL_KEY_{provider.upper()}", "") or legacy.get(provider, "")
    ).strip()


def summary_key() -> str:
    """「报告总结」端点的 API Key：.env 的 MODEL_KEY_SUMMARY，旧键回退 DEEPSEEK_API_KEY。"""
    return (os.getenv("MODEL_KEY_SUMMARY", "") or os.getenv("DEEPSEEK_API_KEY", "")).strip()


def _default_provider() -> str:
    """settings 未记录供应商时的默认值。

    旧版用 NIM（nvapi- 前缀 Key）做截图分析，重构为预设下拉后被默认到千问；
    检测到 nvapi- 键即默认进入自定义双模型模式，否则 dashscope。
    """
    if os.getenv("ANALYZE_API_KEY", "").strip().startswith("nvapi-"):
        return "custom"
    return "dashscope"


def _apply_model_service() -> None:
    """把当前供应商的配置解析进模块级变量（导入时与设置页保存后各执行一次）。

    两种模式：预设供应商下截图分析与日报总结共用一个模型；custom（自定义）
    双模型分开——分析走 model_services["custom"]（Key: MODEL_KEY_CUSTOM），
    总结走 summary_services["custom"]（Key: MODEL_KEY_SUMMARY），未配置的
    字段为空串，由调用方（capture/summarize）给出"去设置页填写"的明确提示。
    经 ANALYZE_* / DEEPSEEK_* 别名兼容既有调用点（含任务计划的独立进程：
    进程启动 import 时即解析）。
    """
    global MODEL_PROVIDER, MODEL_BASE_URL, MODEL_NAME, MODEL_API_KEY
    global ANALYZE_API_KEY, ANALYZE_BASE_URL, ANALYZE_MODEL
    global DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, SUMMARY_MODEL
    if MODEL_PROVIDER not in MODEL_PRESETS:
        MODEL_PROVIDER = _default_provider()
    svc = MODEL_SERVICES.get(MODEL_PROVIDER)
    if not isinstance(svc, dict):
        svc = {}
    if MODEL_PROVIDER == "custom":
        MODEL_BASE_URL = str(svc.get("base_url", "")).strip()
        MODEL_NAME = str(svc.get("model", "")).strip()
        MODEL_API_KEY = model_key_for("custom")
        ssvc = SUMMARY_SERVICES.get("custom")
        if not isinstance(ssvc, dict):
            ssvc = {}
        DEEPSEEK_BASE_URL = str(ssvc.get("base_url", "")).strip()
        SUMMARY_MODEL = str(ssvc.get("model", "")).strip()
        DEEPSEEK_API_KEY = summary_key()
    else:
        # 预设供应商始终用代码里的官方端点，分析与总结共用
        MODEL_BASE_URL = MODEL_PRESETS[MODEL_PROVIDER]["base_url"]
        MODEL_NAME = str(svc.get("model", "")).strip() or MODEL_PRESETS[MODEL_PROVIDER]["default_model"]
        MODEL_API_KEY = model_key_for(MODEL_PROVIDER)
        DEEPSEEK_BASE_URL = MODEL_BASE_URL
        SUMMARY_MODEL = MODEL_NAME
        DEEPSEEK_API_KEY = MODEL_API_KEY

    ANALYZE_API_KEY = MODEL_API_KEY
    ANALYZE_BASE_URL = MODEL_BASE_URL
    ANALYZE_MODEL = MODEL_NAME


MODEL_PROVIDER = str(SETTINGS.get("model_provider", "")).strip() or _default_provider()
_apply_model_service()

# ---------- 问答检索（RAG）：向量化服务 ----------
# 只列确实提供 embedding 模型的供应商（DeepSeek/Kimi 无公开 embeddings 端点）。
# base_url 以代码为准；settings.json 存 embed_provider 与 embed_services:{pid:{model}}，
# Key 走 .env 的 MODEL_KEY_EMBED_<PID>；与对话选了同一家供应商时直接复用那把 Key。
EMBED_PRESETS = {
    "dashscope": {
        "label": "阿里云百炼 · text-embedding-v4",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "text-embedding-v4",
        "hint": "推荐：与百炼对话 Key 通用，新用户含 100 万 Token 免费额度",
    },
    "siliconflow": {
        "label": "硅基流动 · BGE-M3",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "BAAI/bge-m3",
        "hint": "在硅基流动（cloud.siliconflow.cn）获取 API Key",
    },
    "zhipu": {
        "label": "智谱开放平台 · embedding-3",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "embedding-3",
        "hint": "在智谱开放平台（open.bigmodel.cn）获取 API Key",
    },
    "openai": {
        "label": "OpenAI · text-embedding-3-small",
        "base_url": "https://api.openai.com/v1",
        "default_model": "text-embedding-3-small",
        "hint": "在 OpenAI 平台（platform.openai.com）获取 API Key；海外端点需系统代理",
    },
}

EMBED_SERVICES = SETTINGS.get("embed_services")
if not isinstance(EMBED_SERVICES, dict):
    EMBED_SERVICES = {}


def embed_key_for(provider: str) -> str:
    """问答向量化 Key：.env 的 MODEL_KEY_EMBED_<PID> 优先；同供应商已配对话 Key 时复用。"""
    own = os.getenv(f"MODEL_KEY_EMBED_{provider.upper()}", "").strip()
    if own:
        return own
    if provider == MODEL_PROVIDER:
        return model_key_for(provider)
    return ""


def _apply_embed_service() -> None:
    """把当前向量化配置解析进模块级变量（导入时与设置页保存后各执行一次）。"""
    global EMBED_PROVIDER, EMBED_BASE_URL, EMBED_MODEL, EMBED_API_KEY
    provider = str(SETTINGS.get("embed_provider", "")).strip() or "dashscope"
    if provider not in EMBED_PRESETS:
        provider = "dashscope"
    EMBED_PROVIDER = provider
    EMBED_BASE_URL = EMBED_PRESETS[provider]["base_url"]
    svc = EMBED_SERVICES.get(provider)
    model = str(svc.get("model", "")).strip() if isinstance(svc, dict) else ""
    EMBED_MODEL = model or EMBED_PRESETS[provider]["default_model"]
    EMBED_API_KEY = embed_key_for(provider)


_apply_embed_service()

# 问答检索参数
EMBED_BATCH = 10   # 单次 /embeddings 请求的文本条数上限（百炼 text-embedding-v4 限制 10）
ASK_TOP_K = 8      # 每次问答召回的相关片段数
ASK_REWRITE_TURNS = 3     # 检索词改写携带的最近对话轮数（一轮 = 一问一答）
ASK_ANSWER_TURNS = 6      # 回答 prompt 携带的最近对话轮数
ASK_TITLE_MAX_CHARS = 16  # AI 提炼的会话标题长度上限

# 截图分析采样参数（固定常量，与供应商无关；analyze.py 调用点）
ANALYZE_TEMPERATURE = 1
ANALYZE_TOP_P = 0.95
ANALYZE_MAX_TOKENS = 4096
ANALYZE_THINKING = False   # 是否启用推理模型 thinking（deepseek-reasoner 等支持，可设置页开关）

# 截屏调度
MONITOR_INDEX = 1                # mss 监控器编号，1 = 主屏
IDLE_ENABLED = SETTINGS.get("idle_enabled", True)   # 鼠标空闲暂停截屏（可设置页开关）
IDLE_MINUTES = SETTINGS.get("idle_minutes", 5)      # 空闲阈值（分钟）
IDLE_CHOICES = (1, 2, 5, 10, 15, 20, 30)
RETENTION_CHOICES = (0, 7, 14, 30, 60, 90)  # 本地记录保留天数，0 = 永久保留
DEDUP_ENABLED = SETTINGS.get("dedup_enabled", True)  # 跳过重复画面（感知哈希去重开关）
DEDUP_SIG_SIZE = (32, 32)  # 去重签名：降采样灰度图尺寸
DEDUP_HASH_BITS = 12       # dHash 汉明距离阈值（满值 992 位），超过视为画面变化
DEDUP_PIXEL_DIFF = 1.5     # 签名灰度平均像素差阈值（0-255），超过视为画面变化
ENTER_CAPTURE_ENABLED = SETTINGS.get("enter_capture_enabled", False)  # 回车键快速记录
ENTER_CAPTURE_INTERVAL = SETTINGS.get("enter_capture_interval", 15)   # 回车键记录间隔（秒）
ENTER_INTERVAL_CHOICES = (5, 15, 30, 60)  # 回车键记录间隔选项（秒）
MAX_RETRIES = 1                  # API 失败重试次数

# 截图上传压缩（部分模型服务限制请求体大小，原始 4K PNG base64 会超限报 400）
ANALYZE_IMAGE_MAX_SIDE = 1600    # 最长边像素上限
ANALYZE_JPEG_QUALITY = 85        # JPEG 质量

# 目录与状态
RECORDS_DIR = DATA_DIR / "records"
RAW_DIR = RECORDS_DIR / "raw"
REPORTS_DIR = DATA_DIR / "reports"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
TODOS_FILE = RECORDS_DIR / "todos.json"
STATE_FILE = DATA_DIR / "state.json"
SESSIONS_DIR = DATA_DIR / "sessions"  # 问答会话存档（每会话一个 JSON，随每周备份打包）

# 应用使用时长统计（前台窗口采样，任务计划 DailyLogUsage 每 2 分钟驱动一次）
USAGE_DIR = RECORDS_DIR / "usage"
USAGE_INTERVAL_MINUTES = 2  # 采样间隔（分钟），时长按 采样次数 × 间隔 估算
USAGE_ENABLED = SETTINGS.get("usage_enabled", True)  # 设置页可开关

# 自动备份（任务计划 DailyLogBackup 每周驱动一次，core/backup.py 打包 data/）
BACKUP_ENABLED = SETTINGS.get("backup_enabled", True)   # 设置页可开关
BACKUP_DIR = str(SETTINGS.get("backup_dir", ""))        # zip 输出目录，空 = 未启用
BACKUP_WEEKDAY = str(SETTINGS.get("backup_weekday", "SUN"))  # schtasks /d 值：MON..SUN
BACKUP_HOUR = int(SETTINGS.get("backup_hour", 12))      # 触发时刻（整点，24 小时制）
BACKUP_KEEP = int(SETTINGS.get("backup_keep", 5))       # 保留最近 N 份

# WebView2 数据目录固定到用户数据区（pywebview 默认每次启动建随机临时目录且不清理，见 winforms.init_storage）
WEBVIEW_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "dailylog" / "webview"

APP_TITLE = "dailylog · 今日轨迹"  # 应用窗口标题：app.py 创建窗口、capture.py 截屏前按此隐藏自身窗口

# 活动分类 → 时间线中文标签（沿用用户的分类体系）
ACTIVITY_LABELS = {
    "coding": "开发",
    "writing": "文档",
    "meeting": "会议",
    "research": "学习",
    "communication": "沟通",
    "data": "数据分析",
    "support": "运维",
    "browsing": "生活",
    "idle": "其他",
    "other": "其他",
}
