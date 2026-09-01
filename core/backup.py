"""dailylog 入口：把 data/（不含 .env / API Key）打包 zip 到备份目录，并清理超出保留份数的旧备份。

由 Windows 任务计划程序每周调用一次（pythonw 运行，无控制台）；
设置页"立即备份"也直接调 run_backup()。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import zipfile
from datetime import datetime

from core import config

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

_logger = config.setup_logging()

STATE_FILE = config.DATA_DIR / "backup_state.json"
ZIP_PREFIX = "dailylog-backup-"

# 不进备份：.env（明文 API Key，绝不入包）、截图（分析完即删，只剩孤儿文件，可再生）、
# 日志（可再生）、备份状态自身
EXCLUDE_DIRS = {"screenshots", "__pycache__"}
EXCLUDE_FILES = {".env"}
EXCLUDE_PREFIXES = ("dailylog.log", ZIP_PREFIX)


def run_backup() -> dict:
    """打包 data/（不含 .env）到 settings.json 的 backup_dir，保留最近 backup_keep 份。"""
    dest_raw = str(config.SETTINGS.get("backup_dir", "")).strip()
    if not dest_raw:
        _logger.warning("自动备份：未设置备份目录，跳过")
        return {"ok": False, "error": "未设置备份目录"}
    dest = Path(dest_raw)
    try:
        keep = max(1, int(config.SETTINGS.get("backup_keep", 5)))
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        zip_path = dest / f"{ZIP_PREFIX}{stamp}.zip"
        tmp_path = dest / f"{zip_path.name}.tmp"
        files = _collect_files()
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                # 截屏可能与打包并发写 jsonl，读半行最多丢最后一行，不影响历史数据
                zf.write(p, p.relative_to(config.DATA_DIR))
        tmp_path.replace(zip_path)
        kept = _prune_old(dest, keep)
        size_kb = zip_path.stat().st_size // 1024
        _write_state({"last_backup_at": datetime.now().isoformat(timespec="seconds"),
                      "last_ok": True, "last_file": zip_path.name,
                      "last_size_kb": size_kb, "error": ""})
        _logger.info("自动备份：已写入 %s（%d KB），保留 %d 份", zip_path, size_kb, kept)
        return {"ok": True, "path": str(zip_path), "size_kb": size_kb, "kept": kept}
    except (OSError, ValueError) as e:
        _logger.error("自动备份失败: %s", e)
        _write_state({"last_backup_at": datetime.now().isoformat(timespec="seconds"),
                      "last_ok": False, "last_file": "", "last_size_kb": 0,
                      "error": str(e)})
        return {"ok": False, "error": str(e)}


def _collect_files() -> list:
    """data/ 下要打包的文件列表（排除截图/日志/备份状态）。"""
    files = []
    for p in config.DATA_DIR.rglob("*"):
        if not p.is_file() or p == STATE_FILE:
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(config.DATA_DIR).parts[:-1]):
            continue
        if p.name in EXCLUDE_FILES:
            continue
        if p.name.startswith(EXCLUDE_PREFIXES):
            continue
        files.append(p)
    return files


def _prune_old(dest: Path, keep: int) -> int:
    """按文件名（即时间戳）排序，只保留最新 keep 份备份包。"""
    zips = sorted(dest.glob(f"{ZIP_PREFIX}*.zip"))
    for old in zips[:-keep] if len(zips) > keep else []:
        try:
            old.unlink(missing_ok=True)
            _logger.info("自动备份：清理旧包 %s", old.name)
        except OSError as e:
            _logger.warning("自动备份：清理 %s 失败: %s", old.name, e)
    return min(len(zips), keep)


def _write_state(state: dict) -> None:
    """写备份状态（设置页展示上次结果）；失败只记日志，不影响备份结论。"""
    try:
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except OSError as e:
        _logger.warning("自动备份：写状态文件失败: %s", e)


def main() -> int:
    result = run_backup()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
