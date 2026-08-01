"""dailylog 所有可调参数集中在此。"""
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

# 打包后（frozen）数据目录是 exe 所在目录；开发期是源码目录
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def load_settings() -> dict:
    """读取运行时设置（settings.json，UI 可修改；缺省用代码里的默认值）。"""
    try:
        return json.loads((BASE_DIR / "settings.json").read_text(encoding="utf-8"))
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
        BASE_DIR / "dailylog.log",
        maxBytes=1_000_000, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger

# 截图分析 API（阿里云百炼，视觉模型）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ANALYZE_MODEL = "qwen3.5-omni-plus-2026-03-15"

# 日报/周报总结 API（DeepSeek 官方）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SUMMARY_MODEL = "deepseek-v4-flash"

# 截屏调度
MONITOR_INDEX = 1                # mss 监控器编号，1 = 主屏
IDLE_ENABLED = SETTINGS.get("idle_enabled", True)   # 鼠标空闲暂停截屏（可设置页开关）
IDLE_MINUTES = SETTINGS.get("idle_minutes", 5)      # 空闲阈值（分钟）
IDLE_CHOICES = (1, 2, 5, 10, 15, 20, 30)
MAX_RETRIES = 1                  # API 失败重试次数

# 目录与状态
RECORDS_DIR = BASE_DIR / "records"
RAW_DIR = RECORDS_DIR / "raw"
REPORTS_DIR = BASE_DIR / "reports"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
STATE_FILE = BASE_DIR / "state.json"

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
