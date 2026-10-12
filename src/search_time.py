"""从问句解析检索时间窗（覆盖 schedule 默认配置）。"""

from __future__ import annotations

from typing import Any


def resolve_search_window(query: str, search_config: dict[str, Any]) -> dict[str, Any]:
    """根据问句微调 start_after_days / days_ahead。"""
    config = dict(search_config)
    text = query.strip().lower()

    start_after = int(config.get("start_after_days", 0))
    days_ahead = int(config.get("days_ahead", 120))

    if any(k in text for k in ("本周", "这周", "本周末")):
        start_after = 0
        days_ahead = min(days_ahead, 14)
    elif any(k in text for k in ("下周", "下周末")):
        start_after = 7
        days_ahead = min(max(days_ahead, 21), 28)
    elif "下个月" in text:
        start_after = 28
        days_ahead = max(days_ahead, 60)

    config["start_after_days"] = start_after
    config["days_ahead"] = days_ahead
    return config
