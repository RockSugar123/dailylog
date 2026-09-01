"""应用使用时长的数据看板聚合。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from core import config


TREND_RANGES = {"7": 7, "30": 30, "90": 90}


def usage_dashboard(scope: str, anchor: str, trend_range: str) -> dict:
    """返回趋势和星期×小时热力图所需的应用采样统计。"""
    day = _parse_date(anchor)
    current_start, current_end = _scope_range(scope, day)
    trend_start, trend_end = _trend_range(current_start, current_end, day, trend_range)

    trend = _daily_trend(trend_start, trend_end)
    heatmap = _weekly_hour_matrix(current_start, current_end)
    return {
        "ok": True,
        "scope": scope,
        "current_start": current_start.isoformat(),
        "current_end": current_end.isoformat(),
        "trend_range": trend_range,
        "trend": trend,
        "heatmap": heatmap,
    }


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期格式错误") from exc


def _scope_range(scope: str, day: date) -> tuple[date, date]:
    if scope == "week":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    if scope == "month":
        start = day.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return start, end
    return day, day


def _trend_range(start: date, end: date, anchor: date, value: str) -> tuple[date, date]:
    if value == "current":
        return start, end
    days = TREND_RANGES.get(value, 30)
    return anchor - timedelta(days=days - 1), anchor


def _daily_trend(start: date, end: date) -> list[dict]:
    points = []
    day = start
    while day <= end:
        path = _usage_path(day)
        sample_count = _sample_count(path)
        points.append({
            "date": day.isoformat(),
            "minutes": sample_count * config.USAGE_INTERVAL_MINUTES,
            "sampled": path.exists(),
        })
        day += timedelta(days=1)
    return points


def _weekly_hour_matrix(start: date, end: date) -> list[dict]:
    cells = [[{"minutes": 0, "sampled": False} for _ in range(24)] for _ in range(7)]
    day = start
    while day <= end:
        path = _usage_path(day)
        if path.exists():
            weekday_cells = cells[day.weekday()]
            for cell in weekday_cells:
                cell["sampled"] = True
            for record in _read_records(path):
                hour = _hour_from_timestamp(record.get("ts", ""))
                if hour is not None:
                    weekday_cells[hour]["minutes"] += config.USAGE_INTERVAL_MINUTES
        day += timedelta(days=1)

    return [
        {
            "weekday": weekday,
            "hours": cells[weekday],
        }
        for weekday in range(7)
    ]


def _usage_path(day: date) -> Path:
    return config.USAGE_DIR / f"{day:%Y-%m-%d}.jsonl"


def _sample_count(path: Path) -> int:
    return sum(1 for _ in _read_records(path))


def _read_records(path: Path):
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("app"):
                    yield record
    except OSError:
        return


def _hour_from_timestamp(value: str) -> int | None:
    try:
        return datetime.fromisoformat(value).hour
    except ValueError:
        return None
