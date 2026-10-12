"""@机器人 检索：本地 SQLite 搜索 + 可选 Workflow 生成回复。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from datetime import date
from pathlib import Path
from typing import Any

from .event_cache import DEFAULT_CACHE_PATH, EventCache
from .llm_client import WorkflowClient, load_workflow_config
from .scraper.formatter import format_events_preview
from .scraper.models import EventItem
from .search_terms import parse_search_terms
from .search_time import resolve_search_window
from .theme_tags import detect_query_themes, theme_label

logger = logging.getLogger(__name__)


def _log_workflow_fallback(exc: Exception, *, query: str, conversation_mode: str) -> None:
    """记录 Workflow 降级原因；已知错误用 WARNING，未知错误保留 traceback。"""
    if isinstance(exc, requests.exceptions.Timeout):
        logger.warning(
            "Workflow 请求超时，改用本地回复: query=%r mode=%s (%s)",
            query,
            conversation_mode,
            exc,
        )
        return
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if message.startswith("Workflow API HTTP 400:") and "analysis_instructions" in message:
            logger.warning(
                "Workflow 未接受 analysis_instructions 独立变量（请删除 Dify 开始节点该字段，"
                "分析上下文已在 search_meta_json 内）: query=%r mode=%s",
                query,
                conversation_mode,
            )
            return
        if message.startswith("Workflow API HTTP") or message.startswith("Workflow execution failed"):
            logger.warning(
                "Workflow 调用失败，改用本地回复: query=%r mode=%s (%s)",
                query,
                conversation_mode,
                message,
            )
            return
    logger.exception(
        "Workflow 调用出现未知错误，改用本地回复: query=%r mode=%s",
        query,
        conversation_mode,
    )


DEFAULT_SEARCH_HEADER = "【活动检索结果】"
DEFAULT_EMPTY_TEXT = "未找到符合条件的活动，请换个关键词试试。"
WORKFLOW_FALLBACK_FOOTER = (
    "\n\n---\n"
    "⚠️ AI 服务响应超时或暂不可用，以上为本地整理结果。"
    "若需完整 AI 分析，请稍后重试或联系管理员检查 Dify Workflow。"
)
RELAXED_MATCH_PREFIX = (
    "未找到同时满足全部关键词的活动，以下为部分相关结果：\n\n"
)
VECTOR_FALLBACK_PREFIX = (
    "关键词未完全匹配，以下为语义相近的活动：\n\n"
)
SEARCH_FOLLOW_UP_FOOTER = (
    "\n\n---\n"
    "💡 如需 AI 深度分析参展/商机策略，请回复「分析」并补充公司方向，例如：\n"
    "「分析 我们是一家做电子通信的企业，想重点布局香港市场，请给参展建议。」\n"
    "AI 将基于以上活动为你生成：活动价值评估、行业趋势洞察、参展建议、商机对接建议、行动清单。"
)


@dataclass(frozen=True)
class SearchAnswer:
    reply: str
    events: list[EventItem]
    match_mode: str = "none"
    cache_total_in_window: int = 0


def _window_label(search_config: dict[str, Any]) -> str:
    start_after = int(search_config.get("start_after_days", 0))
    days_ahead = int(search_config.get("days_ahead", 120))
    if start_after <= 0:
        return f"今天起 {days_ahead} 天内"
    return f"未来 {start_after}~{days_ahead} 天"


def no_match_reply(
    query: str,
    *,
    search_config: dict[str, Any] | None = None,
    cache_total_in_window: int | None = None,
) -> str:
    config = search_config or {}
    window = _window_label(config)
    total_hint = ""
    if cache_total_in_window is not None:
        total_hint = f"当前库内该时间窗共 {cache_total_in_window} 条活动。"
    return (
        f"抱歉，在{window}的大湾区活动库中，暂未找到与「{query.strip()}」相关的产业商机资讯。"
        f"{total_hint}"
        f"请换个关键词试试，例如：科技、展会、深圳、养老、AI。"
    )


def search_events(
    query: str,
    *,
    cache_path: Path | str | None = None,
    limit: int = 10,
    start_after_days: int = 0,
    days_ahead: int = 365,
    sources: list[str] | None = None,
) -> SearchAnswer:
    cache = EventCache(cache_path or DEFAULT_CACHE_PATH)
    try:
        result = cache.search(
            query,
            limit=limit,
            start_after_days=start_after_days,
            days_ahead=days_ahead,
            sources=sources,
        )
        total = len(
            cache.search(
                "",
                limit=500,
                start_after_days=start_after_days,
                days_ahead=days_ahead,
                sources=sources,
            ).events
        )
        return SearchAnswer(
            events=result.events,
            reply="",
            match_mode=result.match_mode,
            cache_total_in_window=total,
        )
    finally:
        cache.close()


def build_search_meta(
    query: str,
    events: list[EventItem],
    *,
    search_config: dict[str, Any] | None = None,
    user_context: str = "",
    conversation_mode: str = "search",
    match_mode: str = "none",
    cache_total_in_window: int = 0,
) -> dict[str, Any]:
    config = search_config or {}
    days_ahead = int(config.get("days_ahead", 365))
    months = max(1, round(days_ahead / 30))
    start_after = int(config.get("start_after_days", 0))

    terms = parse_search_terms(query)
    query_themes = detect_query_themes(terms.filter_tokens, query)

    return {
        "query": query,
        "matched_count": len(events),
        "cache_total_in_window": cache_total_in_window,
        "coverage_days": days_ahead,
        "coverage_start_after_days": start_after,
        "coverage_window_label": _window_label(config),
        "coverage_months": months,
        "coverage_label": f"未来约 {months} 个月（大湾区活动库）",
        "today": date.today().isoformat(),
        "no_match": len(events) == 0,
        "match_mode": match_mode,
        "relaxed_match": match_mode in {"or_relaxed", "or_relaxed_rerank"},
        "vector_fallback": match_mode == "vector_fallback",
        "hybrid_enabled": match_mode.endswith("_rerank") or match_mode == "vector_fallback",
        "conversation_mode": conversation_mode,
        "user_context": user_context.strip(),
        "query_themes": query_themes,
        "primary_theme": query_themes[0] if query_themes else "",
        "theme_priority_hint": (
            f"请优先展示与「{'、'.join(theme_label(t) for t in query_themes)}」直接相关的活动；"
            "组合主题时优先呈现同时命中多个主题的活动。"
            if query_themes
            else ""
        ),
    }


def build_advise_meta(
    query: str,
    events: list[EventItem],
    *,
    search_config: dict[str, Any] | None = None,
    user_context: str = "",
    match_mode: str = "none",
    cache_total_in_window: int = 0,
    prior_query: str = "",
    prior_reply_preview: str = "",
) -> dict[str, Any]:
    """advise 模式专用 meta：嵌入分析框架、对话历史、活动摘要。"""
    from .analysis_prompt import build_analysis_meta

    base_meta = build_search_meta(
        query,
        events,
        search_config=search_config,
        user_context=user_context,
        conversation_mode="advise",
        match_mode=match_mode,
        cache_total_in_window=cache_total_in_window,
    )
    return build_analysis_meta(
        user_context=user_context,
        events=events,
        prior_query=prior_query,
        prior_reply_preview=prior_reply_preview,
        search_meta=base_meta,
    )


def format_local_reply(
    events: list[EventItem],
    *,
    query: str,
    conversation_mode: str = "search",
    match_mode: str = "none",
) -> str:
    themes = detect_query_themes(parse_search_terms(query).filter_tokens, query)
    header = f"{DEFAULT_SEARCH_HEADER}（关键词：{query.strip() or '全部'}）"
    body = format_events_preview(
        events,
        header=header,
        empty_text=DEFAULT_EMPTY_TEXT,
        query_themes=themes,
    )
    if not events:
        return body
    if match_mode in {"or_relaxed", "or_relaxed_rerank"}:
        body = RELAXED_MATCH_PREFIX + body
    elif match_mode == "vector_fallback":
        body = VECTOR_FALLBACK_PREFIX + body
    return append_search_follow_up(body, conversation_mode=conversation_mode)


def append_search_follow_up(
    reply: str,
    *,
    conversation_mode: str = "search",
    has_matches: bool = True,
) -> str:
    if conversation_mode != "search" or not has_matches:
        return reply
    marker = "💡 如需针对以上活动做参展/商机策略分析"
    if marker in reply:
        return reply
    if DEFAULT_EMPTY_TEXT in reply or "暂未找到" in reply:
        return reply
    return reply.rstrip() + SEARCH_FOLLOW_UP_FOOTER


def answer_query(
    query: str,
    *,
    cache_path: Path | str | None = None,
    search_config: dict[str, Any] | None = None,
    workflow_client: WorkflowClient | None = None,
    user_context: str = "",
    conversation_mode: str = "search",
    events: list[EventItem] | None = None,
    match_mode: str = "none",
    cache_total_in_window: int = 0,
    prior_query: str = "",
    prior_reply_preview: str = "",
) -> SearchAnswer:
    config = resolve_search_window(query, search_config or {})
    if events is None:
        search_result = search_events(
            query,
            cache_path=cache_path,
            limit=int(config.get("max_items", 10)),
            start_after_days=int(config.get("start_after_days", 0)),
            days_ahead=int(config.get("days_ahead", 365)),
            sources=config.get("sources"),
        )
        events = search_result.events
        match_mode = search_result.match_mode
        cache_total_in_window = search_result.cache_total_in_window
    elif conversation_mode == "advise":
        logger.info("Advise mode: using %s events from session (skip re-search)", len(events))

    if conversation_mode == "advise":
        meta = build_advise_meta(
            query,
            events,
            search_config=config,
            user_context=user_context,
            match_mode=match_mode,
            cache_total_in_window=cache_total_in_window,
            prior_query=prior_query,
            prior_reply_preview=prior_reply_preview,
        )
    else:
        meta = build_search_meta(
            query,
            events,
            search_config=config,
            user_context=user_context,
            conversation_mode=conversation_mode,
            match_mode=match_mode,
            cache_total_in_window=cache_total_in_window,
        )

    client = workflow_client
    if client is None:
        wf_config = load_workflow_config()
        if wf_config is not None:
            client = WorkflowClient(wf_config)

    if client is None:
        logger.info("Workflow not configured, using local formatted reply")
        if meta["no_match"]:
            return SearchAnswer(
                reply=no_match_reply(
                    query,
                    search_config=config,
                    cache_total_in_window=cache_total_in_window,
                ),
                events=[],
                match_mode=match_mode,
                cache_total_in_window=cache_total_in_window,
            )
        if conversation_mode == "advise":
            from .analysis_prompt import build_local_analysis

            return SearchAnswer(
                reply=build_local_analysis(
                    user_context=user_context,
                    events=events,
                    prior_query=prior_query,
                ),
                events=events,
                match_mode=match_mode,
                cache_total_in_window=cache_total_in_window,
            )
        return SearchAnswer(
            reply=format_local_reply(
                events,
                query=query,
                conversation_mode=conversation_mode,
                match_mode=match_mode,
            ),
            events=events,
            match_mode=match_mode,
            cache_total_in_window=cache_total_in_window,
        )

    if meta["no_match"]:
        logger.info("No local matches for query=%r, skip workflow and follow-up prompt", query)
        return SearchAnswer(
            reply=no_match_reply(
                query,
                search_config=config,
                cache_total_in_window=cache_total_in_window,
            ),
            events=[],
            match_mode=match_mode,
            cache_total_in_window=cache_total_in_window,
        )

    try:
        reply = client.generate_reply(
            query=query,
            events=events,
            search_meta=meta,
            user_context=user_context,
            conversation_mode=conversation_mode,
        )
        if match_mode in {"or_relaxed", "or_relaxed_rerank"} and RELAXED_MATCH_PREFIX.strip() not in reply:
            reply = RELAXED_MATCH_PREFIX + reply
        if match_mode == "vector_fallback" and VECTOR_FALLBACK_PREFIX.strip() not in reply:
            reply = VECTOR_FALLBACK_PREFIX + reply
        reply = append_search_follow_up(
            reply,
            conversation_mode=conversation_mode,
            has_matches=True,
        )
        return SearchAnswer(
            reply=reply,
            events=events,
            match_mode=match_mode,
            cache_total_in_window=cache_total_in_window,
        )
    except Exception as exc:
        _log_workflow_fallback(exc, query=query, conversation_mode=conversation_mode)
        if conversation_mode == "advise":
            from .analysis_prompt import build_local_analysis

            reply = build_local_analysis(
                user_context=user_context,
                events=events,
                prior_query=prior_query,
            )
        else:
            reply = format_local_reply(
                events,
                query=query,
                conversation_mode=conversation_mode,
                match_mode=match_mode,
            )
        if isinstance(exc, requests.exceptions.Timeout) or (
            isinstance(exc, RuntimeError) and "Workflow" in str(exc)
        ):
            reply = reply.rstrip() + WORKFLOW_FALLBACK_FOOTER
        return SearchAnswer(
            reply=reply,
            events=events,
            match_mode=match_mode,
            cache_total_in_window=cache_total_in_window,
        )
