"""刷新活动缓存：复用爬虫配置，写入 SQLite。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from .event_cache import DEFAULT_CACHE_PATH, EventCache
from .scraper.service import collect_events

logger = logging.getLogger(__name__)


def refresh_event_cache(
    message_config: dict[str, Any],
    *,
    cache_path: Path | str | None = None,
    start_after_days: int | None = None,
    days_ahead: int | None = None,
    max_start_days_ahead: int | None = None,
) -> dict[str, int]:
    """抓取各数据源并 upsert 到本地缓存，同时清理过期记录。"""
    config = dict(message_config)
    if start_after_days is not None:
        config["start_after_days"] = start_after_days
    if days_ahead is not None:
        config["days_ahead"] = days_ahead

    scrape_after = int(config.get("start_after_days", 0))
    scrape_ahead = int(config.get("days_ahead", 365))
    cleanup_ahead = max_start_days_ahead if max_start_days_ahead is not None else scrape_ahead

    logger.info(
        "Refreshing event cache (start_after_days=%s, days_ahead=%s)",
        scrape_after,
        scrape_ahead,
    )
    events = collect_events(config)
    cache = EventCache(cache_path or DEFAULT_CACHE_PATH)
    try:
        upserted = cache.upsert_events(events)
        embedded = cache.update_embeddings(events)
        removed = cache.cleanup(
            remove_started_before_today=True,
            max_start_days_ahead=cleanup_ahead,
        )
        total = cache.count()
    finally:
        cache.close()

    stats = {"fetched": len(events), "upserted": upserted, "embedded": embedded, "removed": removed, "total": total}
    logger.info("Event cache refreshed: %s", stats)
    return stats


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def start_auto_cache_refresh(
    message_config: dict[str, Any],
    *,
    refresh_on_start: bool | None = None,
    interval_hours: float | None = None,
) -> BackgroundScheduler | None:
    """启动时刷新一次，并按间隔后台自动刷新（供 ws --search-reply 使用）。"""
    on_start = (
        refresh_on_start
        if refresh_on_start is not None
        else _env_flag("WS_REFRESH_ON_START", default=True)
    )
    if interval_hours is None:
        interval_hours = float(os.getenv("WS_REFRESH_INTERVAL_HOURS", "24"))

    if on_start:
        logger.info("Auto cache refresh on startup")
        refresh_event_cache(message_config)

    if interval_hours <= 0:
        logger.info("Periodic cache refresh disabled (WS_REFRESH_INTERVAL_HOURS<=0)")
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        refresh_event_cache,
        trigger="interval",
        hours=interval_hours,
        kwargs={"message_config": message_config},
        id="auto-cache-refresh",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduled auto cache refresh every %s hour(s)", interval_hours)
    return scheduler
