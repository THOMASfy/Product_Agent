"""活动去重：已推送过的 event_id 不再重复发送。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


class EventDedupStore:
    def __init__(self, path: Path, max_entries: int = 2000, retention_days: int = 30):
        self.path = path
        self.max_entries = max_entries
        self.retention_days = retention_days
        self._records: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = self._parse_records(data)
            if self._cleanup():
                self.save()
        except (json.JSONDecodeError, OSError):
            self._records = {}

    def _parse_records(self, data: dict[str, Any]) -> dict[str, dict[str, str]]:
        today = date.today().isoformat()
        records = data.get("seen_events")
        if isinstance(records, dict):
            return {
                event_id: {
                    "seen_at": str(record.get("seen_at") or today),
                    "start_date": str(record.get("start_date") or ""),
                    "source": str(record.get("source") or ""),
                }
                for event_id, record in records.items()
                if event_id and isinstance(record, dict)
            }

        # Backward compatibility with the old {"seen_ids": [...]} file format.
        return {
            str(event_id): {"seen_at": today, "start_date": "", "source": ""}
            for event_id in data.get("seen_ids", [])
            if event_id
        }

    def _cleanup(self) -> bool:
        today = date.today()
        stale_before = today - timedelta(days=self.retention_days)
        cleaned: dict[str, dict[str, str]] = {}

        for event_id, record in self._records.items():
            source = record.get("source", "")
            start_date = _parse_date(record.get("start_date", ""))
            seen_at = _parse_date(record.get("seen_at", ""))

            # Event sources stop crawling events after their start date, so their
            # dedup records are only useful until that date.
            if source != "scmp" and start_date and start_date < today:
                continue

            # News/no-date records are bounded by age to keep the file small.
            if (source == "scmp" or not start_date) and seen_at and seen_at < stale_before:
                continue

            cleaned[event_id] = record

        if len(cleaned) > self.max_entries:
            ordered = sorted(
                cleaned.items(),
                key=lambda item: item[1].get("seen_at", ""),
            )
            cleaned = dict(ordered[-self.max_entries :])

        changed = cleaned != self._records
        self._records = cleaned
        return changed

    def save(self) -> None:
        self._cleanup()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"seen_events": self._records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def filter_new(self, event_ids: list[str]) -> list[str]:
        return [eid for eid in event_ids if eid and eid not in self._records]

    def mark_seen_events(self, events: list[Any]) -> None:
        today = date.today().isoformat()
        for event in events:
            event_id = getattr(event, "event_id", "")
            if not event_id:
                continue
            self._records[event_id] = {
                "seen_at": today,
                "start_date": str(getattr(event, "start_date", "") or ""),
                "source": str(getattr(event, "source", "") or ""),
            }
        self.save()


def _parse_date(value: str) -> date | None:
    if not value or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
