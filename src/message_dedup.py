"""@机器人 message_id 去重：持久化，防止飞书重连后重放旧消息。"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

DEFAULT_STORE_PATH = Path("data/seen_message_ids.json")
DEFAULT_TTL_DAYS = 7
DEFAULT_MAX_ITEMS = 5000


def _ttl_seconds() -> int:
    days = max(1, int(os.getenv("WS_MESSAGE_DEDUP_DAYS", str(DEFAULT_TTL_DAYS))))
    return days * 86400


def _max_age_seconds() -> int:
    hours = max(0, int(os.getenv("WS_MESSAGE_MAX_AGE_HOURS", "3")))
    return hours * 3600


def max_message_age_seconds() -> int:
    """超过该秒数的 @ 消息只记日志，不回复（0 表示不限制）。"""
    return _max_age_seconds()


class MessageDedupStore:
    def __init__(
        self,
        *,
        path: Path | str | None = None,
        ttl_seconds: int | None = None,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> None:
        self.path = Path(path or DEFAULT_STORE_PATH)
        self.ttl = ttl_seconds if ttl_seconds is not None else _ttl_seconds()
        self.max_items = max_items
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._seen = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._seen = {}
            return
        if not isinstance(raw, dict):
            self._seen = {}
            return
        now = time.time()
        self._seen = {
            str(key): float(value)
            for key, value in raw.items()
            if now - float(value) <= self.ttl
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._seen, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _purge(self, now: float) -> None:
        expired = [key for key, seen_at in self._seen.items() if now - seen_at > self.ttl]
        for key in expired:
            del self._seen[key]
        while len(self._seen) > self.max_items:
            oldest_key = min(self._seen, key=lambda k: self._seen[k])
            del self._seen[oldest_key]

    def claim(self, message_id: str) -> bool:
        """首次见到返回 True；重复或仍在 TTL 内见过返回 False。"""
        if not message_id:
            return True

        now = time.time()
        with self._lock:
            self._purge(now)
            if message_id in self._seen:
                return False
            self._seen[message_id] = now
            self._save()
            return True


def parse_create_time_ms(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value >= 10**12:
        return value
    if value >= 10**9:
        return value * 1000
    return None


def message_age_seconds(create_time_ms: int | None) -> float | None:
    if not create_time_ms:
        return None
    return max(0.0, time.time() - create_time_ms / 1000)
