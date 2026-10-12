"""根据飞书「发送消息内容结构」文档构造 content 字段。"""

from __future__ import annotations

import json
from typing import Any


def build_post_content(post_body: dict[str, Any]) -> str:
    """构造 post 类型消息的 content（JSON 字符串）。"""
    return json.dumps(post_body, ensure_ascii=False)


def build_text_content(text: str, mentions: list[dict[str, str]] | None = None) -> str:
    """
    构造 text 类型消息的 content（JSON 字符串）。

    @ 用户语法（文档）：
      <at user_id="ou_xxxx">Tom</at>
      <at user_id="all"></at>
    """
    body = text
    if mentions:
        prefix_parts: list[str] = []
        for item in mentions:
            user_id = item["user_id"]
            name = item.get("name", "")
            if user_id == "all":
                prefix_parts.append('<at user_id="all"></at>')
            else:
                prefix_parts.append(f'<at user_id="{user_id}">{name}</at>')
        body = " ".join(prefix_parts) + " " + text

    return json.dumps({"text": body}, ensure_ascii=False)


def _apply_mentions_to_post(post_body: dict[str, Any], mentions: list[dict[str, str]]) -> None:
    zh = post_body.setdefault("zh_cn", {})
    content_rows = zh.setdefault("content", [])
    mention_row: list[dict[str, str]] = []
    for item in mentions:
        user_id = item["user_id"]
        name = item.get("name", "")
        if user_id == "all":
            mention_row.append({"tag": "at", "user_id": "all", "user_name": "所有人"})
        else:
            mention_row.append({"tag": "at", "user_id": user_id, "user_name": name})
    content_rows.insert(0, mention_row)


def build_events_content(
    message: dict[str, Any],
    *,
    skip_if_empty: bool = False,
) -> tuple[str, str] | None:
    """构建活动推送 post 消息；无活动且 skip_if_empty 时返回 None（不发送）。"""
    from .scraper.service import build_events_post, prepare_push_events

    events = prepare_push_events(message, mark_seen=False)
    if not events:
        return None if skip_if_empty else ("post", build_post_content(
            build_events_post(message, events=[], mark_seen=False)
        ))

    post_body = build_events_post(message, events=events, mark_seen=True)
    mentions = message.get("mentions")
    if mentions:
        _apply_mentions_to_post(post_body, mentions)
    return "post", build_post_content(post_body)


def build_content(message: dict[str, Any]) -> tuple[str, str]:
    """根据 schedules.yaml 中的 message 配置返回 (msg_type, content)。"""
    msg_type = message.get("type", "text")

    if msg_type == "text":
        content = build_text_content(
            text=message["text"],
            mentions=message.get("mentions"),
        )
        return msg_type, content

    if msg_type == "events":
        built = build_events_content(message, skip_if_empty=False)
        assert built is not None
        return built

    raise ValueError(f"不支持的消息类型: {msg_type}")
