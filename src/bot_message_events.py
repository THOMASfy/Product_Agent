"""解析飞书 im.message.receive_v1 事件中的 @机器人 文本消息。"""



from __future__ import annotations



import logging

import re

from dataclasses import dataclass

from typing import Any



from .message_parser import parse_message_content, resolve_mention_placeholders



logger = logging.getLogger(__name__)





@dataclass

class ParsedBotMessage:

    chat_id: str

    message_id: str

    message_type: str

    raw_text: str

    user_query: str

    sender_id: str

    create_time_ms: int | None = None





@dataclass(frozen=True)

class MessageResponseDecision:

    should_respond: bool

    reason: str





def _mention_open_id(item: Any) -> str | None:

    if isinstance(item, dict):

        ident = item.get("id")

        if isinstance(ident, dict):

            return ident.get("open_id") or None

        if ident is not None:

            return getattr(ident, "open_id", None) or None

        return item.get("open_id") or None

    ident = getattr(item, "id", None)

    if ident is not None:

        return getattr(ident, "open_id", None) or None

    return None





def _mention_name(item: Any) -> str | None:

    if isinstance(item, dict):

        name = item.get("name")

        return str(name).strip() if name else None

    name = getattr(item, "name", None)

    return str(name).strip() if name else None





def is_mention_all(item: Any) -> bool:

    key = item.get("key") if isinstance(item, dict) else getattr(item, "key", None)

    if key == "@_all":

        return True

    open_id = _mention_open_id(item)

    if open_id == "all":

        return True

    name = _mention_name(item)

    return name in {"所有人", "all", "All"}





def has_mention_all(mentions: list[dict[str, Any]] | None) -> bool:

    """消息是否 @ 了所有人（含飞书把机器人算进 @所有人的情况）。"""

    if not mentions:

        return False

    return any(is_mention_all(item) for item in mentions)





def content_indicates_mention_all(content_raw: str = "", raw_text: str = "") -> bool:

    """从 content / 文本兜底识别 @所有人（mentions 字段缺失时）。"""

    blob = f"{content_raw}\n{raw_text}"

    if not blob.strip():

        return False

    if "@_all" in blob:

        return True

    if re.search(r'"user_id"\s*:\s*"all"', blob):

        return True

    if re.search(r"^@所有人\b", raw_text.strip()):

        return True

    return False





def is_bot_mentioned(

    mentions: list[dict[str, Any]] | None,

    *,

    bot_open_id: str | None = None,

) -> bool:

    """True when the current bot is explicitly @ mentioned (not @所有人)."""

    if not mentions:

        return False

    for item in mentions:

        if is_mention_all(item):

            continue

        mentioned_type = (

            item.get("mentioned_type")

            if isinstance(item, dict)

            else getattr(item, "mentioned_type", None)

        )

        if mentioned_type == "bot":

            return True

        if bot_open_id and _mention_open_id(item) == bot_open_id:

            return True

    return False





def evaluate_message_response(

    *,

    chat_type: str,

    mentions: list[dict[str, Any]] | None,

    bot_open_id: str | None = None,

    content_raw: str = "",

    raw_text: str = "",

) -> MessageResponseDecision:

    """

    群聊回复门槛：

    1. @所有人 → 一律不回复（大群里 @所有人 会包含机器人，不能误触发）

    2. 必须单独 @ 机器人才回复

    单聊（p2p）始终回复。

    """

    if chat_type == "p2p":

        return MessageResponseDecision(True, "p2p")



    if has_mention_all(mentions):

        return MessageResponseDecision(False, "skip_mention_all")



    if content_indicates_mention_all(content_raw, raw_text):

        return MessageResponseDecision(False, "skip_content_mention_all")



    if is_bot_mentioned(mentions, bot_open_id=bot_open_id):

        return MessageResponseDecision(True, "explicit_bot_mention")



    return MessageResponseDecision(False, "skip_no_bot_mention")





def should_respond_to_message(

    *,

    chat_type: str,

    mentions: list[dict[str, Any]] | None,

    bot_open_id: str | None = None,

    content_raw: str = "",

    raw_text: str = "",

) -> bool:

    """群聊必须单独 @ 机器人才回复；@所有人 及普通群消息一律忽略。"""

    return evaluate_message_response(

        chat_type=chat_type,

        mentions=mentions,

        bot_open_id=bot_open_id,

        content_raw=content_raw,

        raw_text=raw_text,

    ).should_respond





def _strip_bot_mentions(text: str) -> str:

    cleaned = re.sub(r"@\S+\s*", " ", text)

    return re.sub(r"\s+", " ", cleaned).strip()





def parse_text_message_event(

    *,

    chat_id: str,

    message_id: str,

    message_type: str,

    content_raw: str,

    mentions: list[dict[str, Any]] | None,

    sender_id: str = "",

    create_time_ms: int | None = None,

) -> ParsedBotMessage | None:

    if message_type != "text":

        logger.info("Skip non-text message_type=%s", message_type)

        return None

    if not chat_id:

        logger.warning("Message event missing chat_id")

        return None



    parsed = parse_message_content("text", content_raw, mentions)

    raw_text = parsed.summary.strip()

    user_query = _strip_bot_mentions(resolve_mention_placeholders(raw_text, mentions))



    return ParsedBotMessage(

        chat_id=chat_id,

        message_id=message_id,

        message_type=message_type,

        raw_text=raw_text,

        user_query=user_query,

        sender_id=sender_id,

        create_time_ms=create_time_ms,

    )

