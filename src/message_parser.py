"""根据飞书「接收消息内容结构」文档解析 body.content。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedMessageContent:
    msg_type: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


def _load_content(content: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    return json.loads(content)


def resolve_mention_placeholders(text: str, mentions: list[dict[str, Any]] | None) -> str:
    """
    将 @_user_X 占位符替换为 @用户名。

    mentions 字段示例：{"key": "@_user_1", "name": "Tom", "id": "ou_xxx"}
    """
    if not mentions:
        return text

    result = text
    for item in mentions:
        key = item.get("key")
        if not key:
            continue
        name = item.get("name") or item.get("id") or key
        result = result.replace(key, f"@{name}")
    return result


def _flatten_post_element(element: dict[str, Any], mentions: list[dict[str, Any]] | None) -> str:
    tag = element.get("tag")
    if tag == "text":
        return element.get("text", "")
    if tag == "a":
        label = element.get("text", element.get("href", ""))
        href = element.get("href", "")
        return f"{label} ({href})" if href else label
    if tag == "at":
        user_id = element.get("user_id", "")
        user_name = element.get("user_name") or resolve_mention_placeholders(user_id, mentions)
        if user_name.startswith("@"):
            return user_name
        return f"@{user_name}" if user_name else resolve_mention_placeholders(user_id, mentions)
    if tag == "img":
        return f"[图片:{element.get('image_key', '')}]"
    if tag == "media":
        return f"[视频:{element.get('file_key', '')}]"
    if tag == "emotion":
        return f"[表情:{element.get('emoji_type', '')}]"
    if tag == "hr":
        return "---"
    if tag == "code_block":
        language = element.get("language", "")
        code = element.get("text", "")
        return f"```{language}\n{code}\n```"
    if tag == "note":
        parts = [_flatten_post_element(child, mentions) for child in element.get("elements", [])]
        return "".join(parts)
    return ""


def parse_post_content(data: dict[str, Any], mentions: list[dict[str, Any]] | None) -> ParsedMessageContent:
    title = data.get("title", "")
    lines: list[str] = []
    for row in data.get("content", []):
        row_text = "".join(_flatten_post_element(el, mentions) for el in row)
        if row_text:
            lines.append(row_text)

    body = "\n".join(lines)
    summary = f"{title}\n{body}".strip() if title else body
    return ParsedMessageContent(msg_type="post", summary=summary, data=data)


def parse_message_content(
    msg_type: str,
    content: str | dict[str, Any],
    mentions: list[dict[str, Any]] | None = None,
) -> ParsedMessageContent:
    """按 msg_type 解析接收到的 content JSON。"""
    data = _load_content(content)

    if msg_type == "text":
        text = resolve_mention_placeholders(data.get("text", ""), mentions)
        return ParsedMessageContent(msg_type="text", summary=text, data=data)

    if msg_type == "post":
        return parse_post_content(data, mentions)

    if msg_type == "image":
        key = data.get("image_key", "")
        return ParsedMessageContent(
            msg_type="image",
            summary=f"[图片] image_key={key}",
            data=data,
        )

    if msg_type == "file":
        name = data.get("file_name", "unknown")
        key = data.get("file_key", "")
        return ParsedMessageContent(
            msg_type="file",
            summary=f"[文件] {name} (file_key={key})",
            data=data,
        )

    if msg_type == "folder":
        name = data.get("file_name", "folder")
        key = data.get("file_key", "")
        return ParsedMessageContent(
            msg_type="folder",
            summary=f"[文件夹] {name} (file_key={key})",
            data=data,
        )

    if msg_type == "audio":
        key = data.get("file_key", "")
        duration = data.get("duration", 0)
        return ParsedMessageContent(
            msg_type="audio",
            summary=f"[音频] {duration}ms (file_key={key})",
            data=data,
        )

    if msg_type == "media":
        name = data.get("file_name", "video")
        key = data.get("file_key", "")
        duration = data.get("duration", 0)
        return ParsedMessageContent(
            msg_type="media",
            summary=f"[视频] {name} {duration}ms (file_key={key})",
            data=data,
        )

    if msg_type == "sticker":
        key = data.get("file_key", "")
        return ParsedMessageContent(
            msg_type="sticker",
            summary=f"[表情包] file_key={key}",
            data=data,
        )

    if msg_type == "interactive":
        title = data.get("title", "")
        return ParsedMessageContent(
            msg_type="interactive",
            summary=f"[卡片] {title}".strip(),
            data=data,
        )

    if msg_type == "share_chat":
        chat_id = data.get("chat_id", "")
        return ParsedMessageContent(
            msg_type="share_chat",
            summary=f"[群名片] chat_id={chat_id}",
            data=data,
        )

    if msg_type == "share_user":
        user_id = data.get("user_id", "")
        return ParsedMessageContent(
            msg_type="share_user",
            summary=f"[个人名片] user_id={user_id}",
            data=data,
        )

    if msg_type == "merge_forward":
        text = data.get("content", "[合并转发消息]")
        return ParsedMessageContent(msg_type="merge_forward", summary=text, data=data)

    if msg_type in {"share_calendar_event", "calendar", "general_calendar"}:
        summary_text = data.get("summary", "")
        return ParsedMessageContent(
            msg_type=msg_type,
            summary=f"[日程] {summary_text}",
            data=data,
        )

    if msg_type == "system":
        template = data.get("template", "")
        return ParsedMessageContent(
            msg_type="system",
            summary=f"[系统消息] {template}",
            data=data,
        )

    if msg_type == "location":
        name = data.get("name", "")
        return ParsedMessageContent(
            msg_type="location",
            summary=f"[位置] {name}",
            data=data,
        )

    if msg_type == "video_chat":
        topic = data.get("topic", "")
        return ParsedMessageContent(msg_type="video_chat", summary=f"[视频通话] {topic}", data=data)

    if msg_type == "todo":
        task_id = data.get("task_id", "")
        return ParsedMessageContent(
            msg_type="todo",
            summary=f"[待办] task_id={task_id}",
            data=data,
        )

    if msg_type == "vote":
        topic = data.get("topic", "")
        options = ", ".join(data.get("options", []))
        return ParsedMessageContent(
            msg_type="vote",
            summary=f"[投票] {topic} ({options})",
            data=data,
        )

    # 未知类型：保留原始 JSON 摘要
    return ParsedMessageContent(
        msg_type=msg_type,
        summary=json.dumps(data, ensure_ascii=False),
        data=data,
    )
