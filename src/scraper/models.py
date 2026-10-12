"""活动数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EventItem:
    event_id: str
    name: str
    date_text: str
    start_date: str
    end_date: str
    organizer: str
    description: str
    location: str
    url: str
    source: str = ""
    topic: str = ""
