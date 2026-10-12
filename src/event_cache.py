"""活动 SQLite 本地缓存：upsert、清理、BM25 检索。"""



from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pathlib import Path



from .event_bm25 import prepare_query_tokens

from .embedding_service import load_embeddings_from_conn, update_event_embeddings
from .hybrid_search import hybrid_rank

from .scraper.filters import event_in_search_window, parse_start_date

from .scraper.models import EventItem

from .search_terms import parse_search_terms



logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class CacheSearchResult:
    events: list[EventItem]
    match_mode: str = "none"



DEFAULT_CACHE_PATH = Path("data/events.db")



_SCHEMA = """

CREATE TABLE IF NOT EXISTS events (

    event_id TEXT PRIMARY KEY,

    name TEXT NOT NULL,

    date_text TEXT NOT NULL DEFAULT '',

    start_date TEXT NOT NULL DEFAULT '',

    end_date TEXT NOT NULL DEFAULT '',

    organizer TEXT NOT NULL DEFAULT '',

    description TEXT NOT NULL DEFAULT '',

    location TEXT NOT NULL DEFAULT '',

    url TEXT NOT NULL DEFAULT '',

    source TEXT NOT NULL DEFAULT '',

    topic TEXT NOT NULL DEFAULT '',

    updated_at TEXT NOT NULL,

    embedding BLOB,

    embedding_text_hash TEXT NOT NULL DEFAULT '',

    embedding_model TEXT NOT NULL DEFAULT ''

);



CREATE INDEX IF NOT EXISTS idx_events_start_date ON events(start_date);

CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

"""





def _now_iso() -> str:

    return datetime.now().isoformat(timespec="seconds")





class EventCache:

    def __init__(self, db_path: Path | str | None = None):

        self.db_path = Path(db_path or DEFAULT_CACHE_PATH)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path)

        self._conn.row_factory = sqlite3.Row

        self._conn.executescript(_SCHEMA)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(events)").fetchall()
        }
        if "topic" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN topic TEXT NOT NULL DEFAULT ''")
            self._conn.commit()
        if "embedding" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN embedding BLOB")
            self._conn.commit()
        if "embedding_text_hash" not in columns:
            self._conn.execute(
                "ALTER TABLE events ADD COLUMN embedding_text_hash TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()
        if "embedding_model" not in columns:
            self._conn.execute(
                "ALTER TABLE events ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()

    def update_embeddings(self, events: list[EventItem]) -> int:
        return update_event_embeddings(self._conn, events)

    def close(self) -> None:

        self._conn.close()



    def upsert_events(self, events: list[EventItem]) -> int:

        if not events:

            return 0



        updated_at = _now_iso()

        rows = [

            (

                event.event_id,

                event.name,

                event.date_text,

                event.start_date,

                event.end_date,

                event.organizer,

                event.description,

                event.location,

                event.url,

                event.source,

                event.topic,

                updated_at,

            )

            for event in events

        ]

        self._conn.executemany(

            """

            INSERT INTO events (

                event_id, name, date_text, start_date, end_date,

                organizer, description, location, url, source, topic, updated_at

            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(event_id) DO UPDATE SET

                name=excluded.name,

                date_text=excluded.date_text,

                start_date=excluded.start_date,

                end_date=excluded.end_date,

                organizer=excluded.organizer,

                description=excluded.description,

                location=excluded.location,

                url=excluded.url,

                source=excluded.source,

                topic=excluded.topic,

                updated_at=excluded.updated_at

            """,

            rows,

        )

        self._conn.commit()

        logger.info("Upserted %d events into cache %s", len(rows), self.db_path)

        return len(rows)



    def cleanup(

        self,

        *,

        today: date | None = None,

        remove_started_before_today: bool = True,

        max_start_days_ahead: int = 365,

    ) -> int:

        today = today or date.today()

        clauses: list[str] = []

        params: list[str] = []



        if remove_started_before_today:

            clauses.append("(start_date != '' AND start_date < ?)")

            params.append(today.isoformat())



        max_start = today + timedelta(days=max_start_days_ahead)

        clauses.append("(start_date != '' AND start_date > ?)")

        params.append(max_start.isoformat())



        if not clauses:

            return 0



        where = " OR ".join(clauses)

        cursor = self._conn.execute(f"DELETE FROM events WHERE {where}", params)

        self._conn.commit()

        deleted = cursor.rowcount

        if deleted:

            logger.info("Removed %d stale events from cache", deleted)

        return deleted



    def count(self) -> int:

        row = self._conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()

        return int(row["c"]) if row else 0



    def search(

        self,

        query: str,

        *,

        limit: int = 10,

        start_after_days: int = 0,

        days_ahead: int = 365,

        sources: list[str] | None = None,

        today: date | None = None,

    ) -> CacheSearchResult:

        today = today or date.today()

        terms = parse_search_terms(query)

        query_tokens = prepare_query_tokens(terms, query)



        sql = "SELECT * FROM events"

        params: list[str | int] = []

        clauses: list[str] = []



        if sources:

            placeholders = ", ".join("?" for _ in sources)

            clauses.append(f"source IN ({placeholders})")

            params.extend(sources)



        if clauses:

            sql += " WHERE " + " AND ".join(clauses)



        rows = self._conn.execute(sql, params).fetchall()

        window_events: list[EventItem] = []



        for row in rows:

            event = _row_to_event(row)

            start = parse_start_date(event.start_date)

            if event_in_search_window(

                event,

                today=today,

                start_after_days=start_after_days,

                days_ahead=days_ahead,

            ):

                window_events.append(event)



        if not query.strip():

            window_events.sort(key=lambda e: (e.start_date or "9999", e.name))

            return CacheSearchResult(window_events[:limit], "bm25")



        if not terms.strict_phrase and not terms.filter_tokens and not query_tokens:

            window_events.sort(key=lambda e: (e.start_date or "9999", e.name))

            return CacheSearchResult(window_events[:limit], "bm25")



        ranked = hybrid_rank(
            window_events,
            query=query,
            terms=terms,
            query_tokens=query_tokens,
            embeddings=load_embeddings_from_conn(
                self._conn,
                [event.event_id for event in window_events],
            ),
            limit=limit,
        )

        return CacheSearchResult(ranked.events, ranked.match_mode)





def _row_to_event(row: sqlite3.Row) -> EventItem:

    return EventItem(

        event_id=row["event_id"],

        name=row["name"],

        date_text=row["date_text"],

        start_date=row["start_date"],

        end_date=row["end_date"],

        organizer=row["organizer"],

        description=row["description"],

        location=row["location"],

        url=row["url"],

        source=row["source"],

        topic=row["topic"] if "topic" in row.keys() else "",

    )

