"""活动日期过滤：仅按开始时间筛选。"""

from __future__ import annotations

from datetime import date, timedelta

from .models import EventItem


def parse_start_date(value: str) -> date | None:
    if not value or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def start_date_in_window(
    start: date | None,
    *,
    today: date,
    start_after_days: int = 7,
    days_ahead: int = 90,
) -> bool:
    """活动是否落在「开始时间」检索窗口内。

    只认 start_date，不看 end_date。例如 6.1–6.8 的活动在 6.7 爬取时会被排除
    （开始时间 6.1 早于 today + start_after_days）。
    """
    if start is None:
        return False
    min_start = today + timedelta(days=start_after_days)
    max_start = today + timedelta(days=days_ahead)
    return min_start <= start <= max_start


def event_in_search_window(
    event: EventItem,
    *,
    today: date,
    start_after_days: int = 0,
    days_ahead: int = 120,
) -> bool:
    """检索时间窗：展会按开始日；SCMP 资讯按发布日（允许近期已发布）。"""
    start = parse_start_date(event.start_date)
    if start is None:
        return False

    if event.source == "scmp":
        earliest = today - timedelta(days=60)
        latest = today + timedelta(days=days_ahead)
        return earliest <= start <= latest

    return start_date_in_window(
        start,
        today=today,
        start_after_days=start_after_days,
        days_ahead=days_ahead,
    )
