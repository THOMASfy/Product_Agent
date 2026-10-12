"""飞书长连接（WebSocket）事件接收服务。"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from .bot_message_events import (
    ParsedBotMessage,
    evaluate_message_response,
    parse_text_message_event,
)
from .feishu_client import FeishuAPIError, FeishuClient
from .llm_client import events_to_json
from .message_builder import build_text_content
from .message_dedup import (
    MessageDedupStore,
    max_message_age_seconds,
    message_age_seconds,
    parse_create_time_ms,
)
from .scraper.models import EventItem
from .search_service import answer_query
from .user_session import (
    advise_without_session_reply,
    events_from_session,
    format_user_text_for_log,
    get_session,
    is_strategy_follow_up,
    save_session,
)

logger = logging.getLogger(__name__)

_MESSAGE_DEDUP = MessageDedupStore()

_CHITCHAT_GREETING_MARKERS = (
    "早上好",
    "晚上好",
    "大家好",
    "各位好",
    "您好",
    "你好",
)
_CHITCHAT_INTRO_MARKERS = (
    "试运行",
    "机器人当前",
    "推送机器人",
    "商机推送",
    "问答功能",
)
_CHITCHAT_USAGE_REPLY = (
    "你好！我是大湾区活动商机推送机器人。\n\n"
    "你可以 @我 并输入关键词检索活动，例如：\n"
    "· 科技 / AI / 展会\n"
    "· 请推荐大湾区科技展会\n"
    "· 本周有什么活动\n\n"
    "收到活动列表后，如需 AI 深度分析，请再次 @我 并发送「分析 …」补充公司方向。"
)


def _mention_list(raw_mentions: Any) -> list[dict[str, Any]] | None:
    if not raw_mentions:
        return None
    items: list[dict[str, Any]] = []
    for item in raw_mentions:
        if isinstance(item, dict):
            items.append(item)
            continue
        mention_id = getattr(item, "id", None)
        open_id = getattr(mention_id, "open_id", None) if mention_id is not None else None
        items.append(
            {
                "key": getattr(item, "key", None),
                "name": getattr(item, "name", None),
                "id": mention_id,
                "open_id": open_id,
                "mentioned_type": getattr(item, "mentioned_type", None),
            }
        )
    return items


def parse_p2_message_receive_v1(data: P2ImMessageReceiveV1) -> ParsedBotMessage | None:
    event = data.event
    if not event or not event.message:
        return None

    message = event.message
    sender = event.sender
    sender_id = ""
    if sender and sender.sender_id:
        sender_id = sender.sender_id.open_id or sender.sender_id.user_id or ""

    return parse_text_message_event(
        chat_id=message.chat_id or "",
        message_id=message.message_id or "",
        message_type=message.message_type or "",
        content_raw=message.content or "{}",
        mentions=_mention_list(message.mentions),
        sender_id=sender_id,
        create_time_ms=parse_create_time_ms(getattr(message, "create_time", None)),
    )


def _is_chitchat_message(query: str) -> bool:
    """长问候/介绍类消息，不应走活动检索。"""
    text = query.strip()
    if len(text) < 40:
        return False
    has_greeting = any(marker in text for marker in _CHITCHAT_GREETING_MARKERS)
    has_intro = any(marker in text for marker in _CHITCHAT_INTRO_MARKERS)
    if not (has_greeting or has_intro):
        return False
    from .search_terms import _is_nl_browse_query

    if _is_nl_browse_query(text) and len(text) < 80:
        return False
    if len(text) < 80 and not has_intro:
        return False
    return True


def _log_parsed_message(parsed: ParsedBotMessage) -> None:
    safe_query = format_user_text_for_log(
        parsed.user_query,
        chat_id=parsed.chat_id,
        sender_id=parsed.sender_id,
    )
    safe_raw = format_user_text_for_log(
        parsed.raw_text,
        chat_id=parsed.chat_id,
        sender_id=parsed.sender_id,
    )
    logger.info(
        "WS handling bot mention -> chat_id=%s message_id=%s raw_text=%r user_query=%r sender=%s",
        parsed.chat_id,
        parsed.message_id,
        safe_raw,
        safe_query,
        parsed.sender_id,
    )


def _send_text_reply(client: FeishuClient, parsed: ParsedBotMessage, text: str) -> None:
    content = build_text_content(text)
    try:
        result = client.send_message_to_chat(parsed.chat_id, "text", content)
        logger.info(
            "Reply sent to chat %s, message_id=%s",
            parsed.chat_id,
            result.get("message_id", "unknown"),
        )
    except FeishuAPIError as exc:
        logger.error(
            "Reply failed for chat %s: Feishu error %s: %s (log_id=%s)",
            parsed.chat_id,
            exc.code,
            exc.msg,
            exc.log_id,
        )


def _search_reply(
    client: FeishuClient,
    parsed: ParsedBotMessage,
    *,
    search_config: dict[str, Any],
) -> None:
    query = parsed.user_query or parsed.raw_text or ""
    if not query.strip():
        _send_text_reply(client, parsed, "请在 @机器人 后输入要检索的关键词，例如：大湾区 展会")
        return

    if _is_chitchat_message(query):
        _send_text_reply(client, parsed, _CHITCHAT_USAGE_REPLY)
        return

    stripped = query.strip()
    if stripped.startswith("分析") and len(stripped) > 2:
        session = get_session(parsed.chat_id, parsed.sender_id)
        if not session or not events_from_session(session.get("events") or []):
            _send_text_reply(client, parsed, advise_without_session_reply())
            return

    conversation_mode = "search"
    user_context = ""
    effective_query = query
    advise_events: list[EventItem] | None = None

    prior = get_session(parsed.chat_id, parsed.sender_id)
    if prior and is_strategy_follow_up(query, has_session=True):
        conversation_mode = "advise"
        # 去掉「分析」前缀，只保留用户补充的公司/方向信息
        cleaned_context = query.strip()
        for prefix in ("分析：", "分析:", "分析"):
            if cleaned_context.startswith(prefix) and len(cleaned_context) > len(prefix):
                cleaned_context = cleaned_context[len(prefix):].strip()
                break
        user_context = cleaned_context or query
        effective_query = str(prior.get("query") or query)
        prior_reply_preview = str(prior.get("reply_preview") or "")
        advise_events = events_from_session(prior.get("events") or [])
        if advise_events:
            logger.info(
                "Strategy follow-up from sender=%s prior_query=%r session_events=%s",
                parsed.sender_id,
                prior.get("query"),
                len(advise_events),
            )
        else:
            logger.warning(
                "Advise follow-up from sender=%s but session has no events",
                parsed.sender_id,
            )
            _send_text_reply(client, parsed, advise_without_session_reply())
            return

        answer = answer_query(
            effective_query,
            search_config=search_config,
            user_context=user_context,
            conversation_mode=conversation_mode,
            events=advise_events if advise_events else None,
            prior_query=str(prior.get("query") or ""),
            prior_reply_preview=prior_reply_preview,
        )
    else:
        answer = answer_query(
            effective_query,
            search_config=search_config,
            user_context=user_context,
            conversation_mode=conversation_mode,
            events=advise_events if advise_events else None,
        )
    _send_text_reply(client, parsed, answer.reply)

    if conversation_mode == "search" and answer.events:
        save_session(
            chat_id=parsed.chat_id,
            sender_id=parsed.sender_id,
            query=effective_query,
            events=json.loads(events_to_json(answer.events)),
            reply_preview=answer.reply,
        )


def _run_reply_async(
    *,
    client: FeishuClient,
    parsed: ParsedBotMessage,
    search_config: dict[str, Any],
) -> None:
    def work() -> None:
        try:
            _search_reply(client, parsed, search_config=search_config)
        except Exception:
            logger.exception("Async reply failed for message_id=%s", parsed.message_id)

    threading.Thread(
        target=work,
        daemon=True,
        name=f"feishu-reply-{parsed.message_id or 'unknown'}",
    ).start()


def build_event_handler(
    *,
    feishu_client: FeishuClient,
    search_config: dict[str, Any],
    bot_open_id: str | None = None,
) -> lark.EventDispatcherHandler:
    def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
        message = data.event.message if data.event else None
        if not message:
            return

        chat_type = getattr(message, "chat_type", "") or ""
        mentions = _mention_list(getattr(message, "mentions", None))
        content_raw = message.content or "{}"
        decision = evaluate_message_response(
            chat_type=chat_type,
            mentions=mentions,
            bot_open_id=bot_open_id,
            content_raw=content_raw,
        )
        if not decision.should_respond:
            logger.debug(
                "Skip message chat_id=%s message_id=%s chat_type=%s reason=%s",
                message.chat_id or "",
                message.message_id or "",
                chat_type,
                decision.reason,
            )
            return

        parsed = parse_p2_message_receive_v1(data)
        if parsed:

            if not _MESSAGE_DEDUP.claim(parsed.message_id):
                safe_query = format_user_text_for_log(
                    parsed.user_query,
                    chat_id=parsed.chat_id,
                    sender_id=parsed.sender_id,
                )
                logger.info(
                    "Skip duplicate @bot message message_id=%s user_query=%r",
                    parsed.message_id,
                    safe_query,
                )
                return

            max_age = max_message_age_seconds()
            age = message_age_seconds(parsed.create_time_ms)
            if max_age > 0 and age is not None and age > max_age:
                logger.info(
                    "Skip stale @bot message message_id=%s age=%.0fs (max=%ss) user_query=%r",
                    parsed.message_id,
                    age,
                    max_age,
                    format_user_text_for_log(
                        parsed.user_query,
                        chat_id=parsed.chat_id,
                        sender_id=parsed.sender_id,
                    ),
                )
                return

            _log_parsed_message(parsed)
            _run_reply_async(
                client=feishu_client,
                parsed=parsed,
                search_config=search_config,
            )
        else:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("WS raw event: %s", lark.JSON.marshal(data, indent=2))
            message = data.event.message if data.event else None
            message_type = getattr(message, "message_type", None) if message else None
            logger.info(
                "WS event received but not handled as text message (message_type=%s)",
                message_type,
            )

    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
        .build()
    )


def run_ws_client(
    *,
    app_id: str,
    app_secret: str,
    log_level: lark.LogLevel | None = None,
    search_config: dict[str, Any],
    cache_message_config: dict[str, Any] | None = None,
    feishu_client: FeishuClient,
    skip_cache_refresh: bool = False,
) -> None:
    level = log_level or lark.LogLevel.INFO

    if cache_message_config and not skip_cache_refresh:
        from .cache_service import start_auto_cache_refresh

        start_auto_cache_refresh(cache_message_config)

    logger.warning(
        "Feishu allows only ONE long-connection client per app. "
        "Stop duplicate `main.py ws` / `main.py serve` processes before testing."
    )
    bot_open_id = os.getenv("FEISHU_BOT_OPEN_ID", "").strip() or None
    event_handler = build_event_handler(
        feishu_client=feishu_client,
        search_config=search_config,
        bot_open_id=bot_open_id,
    )
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=level,
    )
    logger.info("Starting Feishu long-connection client (im.message.receive_v1, search-reply)")
    client.start()


def load_schedule_target(config_path: Path, schedule_name: str) -> dict[str, Any]:
    from .scheduler_service import load_schedules

    schedules = load_schedules(config_path)
    target = next((s for s in schedules if s.get("name") == schedule_name), None)
    if not target:
        raise ValueError(f"未找到名为 '{schedule_name}' 的任务")
    return target


def load_search_config_from_schedule(config_path: Path, schedule_name: str) -> dict[str, Any]:
    target = load_schedule_target(config_path, schedule_name)
    message = dict(target.get("message") or {})
    return {
        "sources": message.get("sources") or ([message["source"]] if message.get("source") else None),
        "start_after_days": int(message.get("start_after_days", 7)),
        "days_ahead": int(message.get("days_ahead", 60)),
        "max_items": int(message.get("max_items", 10)),
    }
