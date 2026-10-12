"""@机器人 多轮对话：按群+用户暂存上一轮问答，供战略建议跟进。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .scraper.models import EventItem

DEFAULT_SESSION_PATH = Path("data/bot_sessions.json")
SESSION_TTL_SECONDS = int(os.getenv("BOT_SESSION_TTL_SECONDS", str(2 * 60 * 60)))
ADVISE_MIN_CHARS = 20


def advise_without_session_reply() -> str:
    return (
        "请先 @机器人 检索关键词（例如：科技、AI、展会），收到活动列表后再 @机器人 发送：\n"
        "「分析 我们是一家…企业，想布局香港市场，请给参展建议。」\n"
        f"分析会基于上一轮检索结果生成，session 有效期约 {SESSION_TTL_SECONDS // 60} 分钟。"
    )


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def session_key(chat_id: str, sender_id: str) -> str:
    return f"{chat_id}:{sender_id or 'unknown'}"


def get_session(chat_id: str, sender_id: str, *, path: Path | None = None) -> dict[str, Any] | None:
    store = _load(path or DEFAULT_SESSION_PATH)
    item = store.get(session_key(chat_id, sender_id))
    if not item:
        return None
    if time.time() - float(item.get("updated_at", 0)) > SESSION_TTL_SECONDS:
        return None
    return item


def save_session(
    *,
    chat_id: str,
    sender_id: str,
    query: str,
    events: list[dict[str, Any]],
    reply_preview: str = "",
    path: Path | None = None,
) -> None:
    p = path or DEFAULT_SESSION_PATH
    store = _load(p)
    key = session_key(chat_id, sender_id)
    store[key] = {
        "query": query,
        "events": events,
        "reply_preview": reply_preview[:500],
        "updated_at": time.time(),
    }
    _save(p, store)


def events_from_session(raw: list[Any]) -> list[EventItem]:
    """将 session 中存的 events 列表还原为 EventItem（advise 模式用）。"""
    items: list[EventItem] = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("event_id"):
            continue
        items.append(
            EventItem(
                event_id=str(entry.get("event_id", "")),
                name=str(entry.get("name", "")),
                date_text=str(entry.get("date_text", "")),
                start_date=str(entry.get("start_date", "")),
                end_date=str(entry.get("end_date", "")),
                organizer=str(entry.get("organizer", "")),
                description=str(entry.get("description", "")),
                location=str(entry.get("location", "")),
                url=str(entry.get("url", "")),
                source=str(entry.get("source", "")),
                topic=str(entry.get("topic", "")),
            )
        )
    return items


def is_strategy_follow_up(text: str, *, has_session: bool = False) -> bool:
    """用户是否在补充公司方向/战略（第二轮 advise 咨询）。"""
    stripped = text.strip()
    if not stripped or not has_session:
        return False

    # 显式指令：以「分析」开头（@机器人 后的正文）
    body = stripped.lstrip()
    for prefix in ("分析", "分析：", "分析:"):
        if body.startswith(prefix) and len(body) > len(prefix):
            return True

    # 有上一轮检索 session 且补充足够长 → 默认进入 advise
    if len(stripped) >= ADVISE_MIN_CHARS:
        return True

    if len(stripped) < 12:
        return False

    markers = (
        "战略",
        "方向",
        "目标",
        "规划",
        "我们公司",
        "我们团队",
        "主营业务",
        "业务方向",
        "出海",
        "布局",
        "建议",
        "推荐",
        "适合",
    )
    return any(marker in stripped for marker in markers)


def format_user_text_for_log(
    text: str,
    *,
    chat_id: str,
    sender_id: str,
) -> str:
    """advise 战略追问不写全文到日志，只记长度。"""
    if not text:
        return text
    session = get_session(chat_id, sender_id)
    if is_strategy_follow_up(text, has_session=session is not None):
        return f"[advise redacted, {len(text)} chars]"
    return text
