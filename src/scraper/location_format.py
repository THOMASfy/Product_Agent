"""活动地点字段规范化（含 HKTDC JSON 结构）。"""

from __future__ import annotations

import ast
import json
from typing import Any

from .models import EventItem


def _names_from_region_list(items: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(items, list):
        return names
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("NAME") or item.get("name") or "").strip()
            if name:
                names.append(name)
        elif isinstance(item, str) and item.strip():
            names.append(item.strip())
    return names


def _names_from_mapping(data: dict[str, Any]) -> list[str]:
    for key in ("region_display", "region", "regionsForDisplay", "regions"):
        names = _names_from_region_list(data.get(key))
        if names:
            return names
    return []


def _parse_location_payload(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return []
        if isinstance(data, dict):
            return _names_from_mapping(data)
    return []


def format_location_text(location: str, *, source: str = "") -> str:
    raw = (location or "").strip()
    if not raw:
        if source == "discoverhongkong":
            return "香港"
        if source == "scmp":
            return "新闻资讯"
        return "地点待定"

    parsed = _parse_location_payload(raw)
    if parsed:
        return "、".join(dict.fromkeys(parsed))

    if raw.startswith("{") and "NAME" in raw:
        return "地点待定"

    return raw


def format_event_location(event: EventItem) -> str:
    return format_location_text(event.location, source=event.source)
