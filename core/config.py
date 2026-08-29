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

# 截图分析 API（DeepSeek 官方多模态模型，OpenAI 兼容端点）
# 未单独填 ANALYZE_API_KEY 时回退用 DEEPSEEK_API_KEY，只申请一个 DeepSeek Key 即可全跑通
ANALYZE_API_KEY = os.getenv("ANALYZE_API_KEY", "").strip() or os.getenv("DEEPSEEK_API_KEY", "").strip()
ANALYZE_BASE_URL = "https://api.deepseek.com"
ANALYZE_MODEL = "deepseek-v4-flash-vision-exp"
ANALYZE_TEMPERATURE = 1
ANALYZE_TOP_P = 0.95
ANALYZE_MAX_TOKENS = 4096
ANALYZE_THINKING = False  # 截图分析禁用思考模式：更快更省，结构化 JSON 输出足够

# 日报/周报总结 API（DeepSeek 官方，与截图分析共用同一模型）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SUMMARY_MODEL = "deepseek-v4-flash-vision-exp"

# 截屏调度
MONITOR_INDEX = 1                # mss 监控器编号，1 = 主屏
IDLE_ENABLED = SETTINGS.get("idle_enabled", True)   # 鼠标空闲暂停截屏（可设置页开关）
IDLE_MINUTES = SETTINGS.get("idle_minutes", 5)      # 空闲阈值（分钟）
IDLE_CHOICES = (1, 2, 5, 10, 15, 20, 30)
RETENTION_CHOICES = (0, 7, 14, 30, 60, 90)  # 本地记录保留天数，0 = 永久保留
DEDUP_ENABLED = SETTINGS.get("dedup_enabled", True)  # 跳过重复画面（md5 去重开关）
ENTER_CAPTURE_ENABLED = SETTINGS.get("enter_capture_enabled", False)  # 回车键快速记录
ENTER_CAPTURE_INTERVAL = SETTINGS.get("enter_capture_interval", 15)   # 回车键记录间隔（秒）
ENTER_INTERVAL_CHOICES = (5, 15, 30, 60)  # 回车键记录间隔选项（秒）
MAX_RETRIES = 1                  # API 失败重试次数

# 截图上传压缩（NIM 限制请求体大小，原始 4K PNG base64 会超限报 400）
ANALYZE_IMAGE_MAX_SIDE = 1600    # 最长边像素上限
ANALYZE_JPEG_QUALITY = 85        # JPEG 质量

# 目录与状态
RECORDS_DIR = DATA_DIR / "records"
RAW_DIR = RECORDS_DIR / "raw"
REPORTS_DIR = DATA_DIR / "reports"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
TODOS_FILE = RECORDS_DIR / "todos.json"
STATE_FILE = DATA_DIR / "state.json"

# 应用使用时长统计（前台窗口采样，任务计划 DailyLogUsage 每 2 分钟驱动一次）
USAGE_DIR = RECORDS_DIR / "usage"
USAGE_INTERVAL_MINUTES = 2  # 采样间隔（分钟），时长按 采样次数 × 间隔 估算
USAGE_ENABLED = SETTINGS.get("usage_enabled", True)  # 设置页可开关

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
