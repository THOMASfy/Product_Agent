"""活动抓取与消息生成服务。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .dedup import EventDedupStore
from .discoverhongkong import fetch_events as fetch_dhk_events
from .formatter import format_events_post
from .hktdc import fetch_events as fetch_hktdc_events
from .models import EventItem
from .scmp import fetch_events as fetch_scmp_events
from .zhandaren import fetch_events as fetch_zhandaren_events

DEFAULT_DEDUP_PATH = Path("data/seen_events.json")
logger = logging.getLogger(__name__)


def _sort_key(event: EventItem, *, source: str | None = None) -> tuple[str, str]:
    source_name = source or event.source
    if source_name == "scmp":
        return (event.start_date or "0000", event.name)
    return (event.start_date or "9999", event.name)


def _sort_events(
    events: list[EventItem],
    message_config: dict[str, Any],
) -> list[EventItem]:
    sources = message_config.get("sources") or []
    if message_config.get("priority_sources") and sources:
        ordered: list[EventItem] = []
        for source in sources:
            source_events = [event for event in events if event.source == source]
            source_events.sort(
                key=lambda event, source=source: _sort_key(event, source=source),
                reverse=source == "scmp",
            )
            ordered.extend(source_events)
        return ordered

    if message_config.get("source") == "scmp":
        return sorted(events, key=lambda e: _sort_key(e, source="scmp"), reverse=True)
    return sorted(events, key=_sort_key)


def _prepare_events(
    message_config: dict[str, Any],
    *,
    dedup_path: Path | None = None,
    mark_seen: bool = True,
    events: list[EventItem] | None = None,
) -> list[EventItem]:
    if events is None:
        events = collect_events(message_config)
    max_items = int(message_config.get("max_items", 5))
    only_new = message_config.get("only_new", True)

    events = _sort_events(events, message_config)

    if only_new:
        store = EventDedupStore(dedup_path or DEFAULT_DEDUP_PATH)
        new_ids = store.filter_new([e.event_id for e in events])
        events = [e for e in events if e.event_id in new_ids]

    events = events[:max_items]

    if only_new and mark_seen and events:
        store = EventDedupStore(dedup_path or DEFAULT_DEDUP_PATH)
        store.mark_seen_events(events)

    return events


def collect_events(message_config: dict[str, Any]) -> list[EventItem]:
    start_after_days = int(message_config.get("start_after_days", 7))
    days_ahead = int(message_config.get("days_ahead", 90))

    sources = message_config.get("sources")
    if sources:
        events: list[EventItem] = []
        for source in sources:
            try:
                events.extend(
                    _collect_from_source(
                        source,
                        message_config,
                        start_after_days=start_after_days,
                        days_ahead=days_ahead,
                    )
                )
            except Exception as exc:
                logger.warning("数据源 %s 抓取失败，已跳过：%s", source, exc)
        return events

    source = message_config.get("source", "discoverhongkong")
    return _collect_from_source(
        source,
        message_config,
        start_after_days=start_after_days,
        days_ahead=days_ahead,
    )


def _collect_from_source(
    source: str,
    message_config: dict[str, Any],
    *,
    start_after_days: int,
    days_ahead: int,
) -> list[EventItem]:
    if source == "discoverhongkong":
        return fetch_dhk_events(
            days_ahead=days_ahead,
            start_after_days=start_after_days,
            exclude_keywords=message_config.get("exclude_keywords"),
            require_include_keywords=message_config.get("dhk_require_include", False),
        )

    if source == "hktdc":
        return fetch_hktdc_events(
            days_ahead=days_ahead,
            start_after_days=start_after_days,
            languages=message_config.get("hktdc_languages"),
        )

    if source == "zhandaren":
        return fetch_zhandaren_events(
            days_ahead=days_ahead,
            start_after_days=start_after_days,
            include_hong_kong_page=message_config.get("include_hong_kong_page", True),
        )

    if source == "scmp":
        return fetch_scmp_events(
            max_results=int(message_config.get("search_results", 20)),
            translate_summaries=message_config.get("scmp_translate", True),
            per_query=int(message_config.get("scmp_per_query", 8)),
        )

    raise ValueError(f"不支持的数据源: {source}")


def _events_from_cache(message_config: dict[str, Any]) -> list[EventItem]:
    """推送前从刚刷新的 SQLite 读取活动，避免再跑一遍全量爬虫。"""
    from ..event_cache import DEFAULT_CACHE_PATH, EventCache

    sources = message_config.get("sources")
    if not sources:
        sources = [message_config.get("source", "discoverhongkong")]

    cache = EventCache(DEFAULT_CACHE_PATH)
    try:
        result = cache.search(
            "",
            limit=10_000,
            start_after_days=int(message_config.get("start_after_days", 7)),
            days_ahead=int(message_config.get("days_ahead", 90)),
            sources=list(sources),
        )
        return result.events
    finally:
        cache.close()


def prepare_push_events(
    message_config: dict[str, Any],
    *,
    dedup_path: Path | None = None,
    mark_seen: bool = False,
) -> list[EventItem]:
    """定时推送前：刷新缓存并筛选待推送活动（默认不 mark seen，发送成功后再标记）。"""
    from ..cache_service import refresh_event_cache

    refresh_event_cache(message_config)
    events = _events_from_cache(message_config)
    return _prepare_events(
        message_config,
        dedup_path=dedup_path,
        mark_seen=mark_seen,
        events=events,
    )


def build_events_post(
    message_config: dict[str, Any],
    *,
    dedup_path: Path | None = None,
    mark_seen: bool = True,
    events: list[EventItem] | None = None,
) -> dict:
    if events is None:
        events = prepare_push_events(message_config, dedup_path=dedup_path, mark_seen=mark_seen)
    elif mark_seen and events and message_config.get("only_new", True):
        store = EventDedupStore(dedup_path or DEFAULT_DEDUP_PATH)
        store.mark_seen_events(events)

    return format_events_post(
        events,
        header=message_config.get("header", "【香港活动日历】"),
        empty_text=message_config.get("empty_text", "今日暂无新活动。"),
        footer_link=message_config.get("footer_link"),
    )
