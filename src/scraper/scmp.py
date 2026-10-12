"""South China Morning Post search scraper."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta, timezone
from html import unescape
from typing import Any

import requests

from ..translate_util import translate_to_chinese
from .models import EventItem
from .scmp_topics import (
    SCMP_TOPICS,
    ScmpTopic,
    classify_scmp_event,
    scmp_topic_priority,
    topic_matches_raw_article,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.scmp.com"
SEARCH_URL = f"{BASE_URL}/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HK_TZ = timezone(timedelta(hours=8))

MAIN_CHUNK = re.compile(r'https://assets-v2\.i-scmp\.com/production/_next/static/chunks/main-[^"]+\.js')
CONTENT_SERVICE = re.compile(
    r'graphql:\{contentService:\{apiKey:"([^"]+)",host:"([^"]+)"'
)
HTML_TAG = re.compile(r"<[^>]+>")

GRAPHQL_QUERY = """
query ScmpSearch($query: String!, $first: Int = 20) {
  articleSearch(
    filter: {query: $query}
    orderBy: {field: PUBLISHED_DATE, direction: DESC}
    first: $first
  ) {
    edges {
      node {
        content {
          __typename
          entityId
          headline
          publishedDate
          urlAlias
          summary {
            text
          }
        }
      }
    }
  }
}
""".strip()


def _clean_text(value: str | None) -> str:
    value = unescape(value or "")
    value = HTML_TAG.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip()


def _format_published_date(value: Any) -> tuple[str, str]:
    try:
        timestamp = int(value) / 1000
    except (TypeError, ValueError):
        return "", ""

    published = datetime.fromtimestamp(timestamp, UTC).astimezone(HK_TZ)
    date_value = published.date().isoformat()
    return date_value, published.strftime("%Y-%m-%d %H:%M")


def _absolute_url(url_alias: str | None) -> str:
    if not url_alias:
        return BASE_URL
    if url_alias.startswith("http://") or url_alias.startswith("https://"):
        return url_alias
    return f"{BASE_URL}{url_alias if url_alias.startswith('/') else '/' + url_alias}"


def _resolve_content_service(session: requests.Session, *, query: str) -> tuple[str, str]:
    response = session.get(
        SEARCH_URL,
        params={"q": query},
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=45,
    )
    response.raise_for_status()

    chunk_match = MAIN_CHUNK.search(response.text)
    if not chunk_match:
        raise RuntimeError("未能在 SCMP 搜索页找到 main JS chunk")

    chunk_response = session.get(chunk_match.group(0), timeout=45)
    chunk_response.raise_for_status()

    service_match = CONTENT_SERVICE.search(chunk_response.text)
    if not service_match:
        raise RuntimeError("未能在 SCMP 配置中找到 content service")

    return service_match.group(2), service_match.group(1)


def _iter_contents(data: dict[str, Any]) -> list[dict[str, Any]]:
    edges = (
        data.get("data", {})
        .get("articleSearch", {})
        .get("edges", [])
    )
    contents: list[dict[str, Any]] = []
    for edge in edges:
        content = edge.get("node", {}).get("content")
        if isinstance(content, dict):
            contents.append(content)
    return contents


def _search_articles(
    session: requests.Session,
    *,
    endpoint: str,
    api_key: str,
    query: str,
    max_results: int,
) -> list[dict[str, Any]]:
    response = session.post(
        endpoint,
        headers={"apikey": api_key, "Content-Type": "application/json"},
        json={
            "operationName": "ScmpSearch",
            "query": GRAPHQL_QUERY,
            "variables": {"query": query, "first": max_results},
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"SCMP GraphQL error: {payload['errors']}")
    return _iter_contents(payload)


def _content_to_event(
    content: dict[str, Any],
    *,
    translate_summaries: bool,
    topic_label: str = "",
) -> EventItem | None:
    headline = _clean_text(content.get("headline"))
    summary = _clean_text((content.get("summary") or {}).get("text"))
    if not headline:
        return None

    if translate_summaries:
        headline = translate_to_chinese(headline)
        if summary:
            summary = translate_to_chinese(summary)

    start_date, published_text = _format_published_date(content.get("publishedDate"))
    entity_id = str(content.get("entityId") or content.get("urlAlias") or headline)
    return EventItem(
        event_id=f"scmp-{entity_id}",
        name=headline,
        date_text=f"发布时间:{published_text}" if published_text else "发布时间:待定",
        start_date=start_date,
        end_date="",
        organizer="South China Morning Post",
        description=summary,
        location="",
        url=_absolute_url(content.get("urlAlias")),
        source="scmp",
        topic=topic_label,
    )


def _sort_scmp_events(events: list[EventItem]) -> list[EventItem]:
    events.sort(key=lambda event: (event.start_date or "0000", event.name), reverse=True)
    events.sort(
        key=lambda event: scmp_topic_priority(event.topic or classify_scmp_event(event))
    )
    return events


def _fetch_topic_lane(
    session: requests.Session,
    *,
    endpoint: str,
    api_key: str,
    topic: ScmpTopic,
    per_query: int,
    translate_summaries: bool,
    seen_ids: set[str],
    events: list[EventItem],
) -> None:
    for query in topic.queries:
        try:
            contents = _search_articles(
                session,
                endpoint=endpoint,
                api_key=api_key,
                query=query,
                max_results=per_query,
            )
        except Exception:
            logger.exception("SCMP topic=%s query failed: %s", topic.label, query)
            continue

        for content in contents:
            entity_id = str(content.get("entityId") or "")
            if entity_id and entity_id in seen_ids:
                continue

            headline = _clean_text(content.get("headline"))
            summary = _clean_text((content.get("summary") or {}).get("text"))
            if not headline:
                continue
            if not topic_matches_raw_article(headline=headline, summary=summary, topic=topic):
                continue

            event = _content_to_event(
                content,
                translate_summaries=translate_summaries,
                topic_label=topic.label,
            )
            if event is None:
                continue
            if entity_id:
                seen_ids.add(entity_id)
            events.append(event)


def fetch_events(
    *,
    query: str | None = None,
    keywords: list[str] | None = None,
    extra_queries: list[str] | None = None,
    max_results: int = 20,
    translate_summaries: bool = True,
    per_query: int | None = None,
) -> list[EventItem]:
    """按主题分桶搜索 SCMP，排除财经商业，保留科技/出海/内地香港等方向。

    query / keywords / extra_queries 参数保留兼容旧配置，新逻辑以 scmp_topics 为准。
    """
    del query, keywords, extra_queries

    per_query = per_query or max(6, min(12, max_results // 2))
    bootstrap_query = SCMP_TOPICS[0].queries[0]

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{SEARCH_URL}?q={bootstrap_query}",
        }
    )

    try:
        endpoint, api_key = _resolve_content_service(session, query=bootstrap_query)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        logger.warning(
            "SCMP 搜索页被拒绝（HTTP %s），本轮跳过该源。站点可能开启了反爬。",
            status,
        )
        return []

    events: list[EventItem] = []
    seen_ids: set[str] = set()

    for topic in SCMP_TOPICS:
        _fetch_topic_lane(
            session,
            endpoint=endpoint,
            api_key=api_key,
            topic=topic,
            per_query=per_query,
            translate_summaries=translate_summaries,
            seen_ids=seen_ids,
            events=events,
        )

    events = _sort_scmp_events(events)
    topic_counts: dict[str, int] = {}
    for event in events:
        label = event.topic or classify_scmp_event(event) or "其他"
        topic_counts[label] = topic_counts.get(label, 0) + 1

    logger.info(
        "SCMP matched %d articles by topic lanes: %s",
        len(events),
        ", ".join(f"{k}={v}" for k, v in topic_counts.items()) or "none",
    )
    return events
