"""活动语义向量：模型加载、编码、持久化辅助。"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .scraper.models import EventItem

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def hybrid_search_enabled() -> bool:
    if not _env_flag("HYBRID_SEARCH_ENABLED", default=True):
        return False
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        logger.warning("HYBRID_SEARCH_ENABLED but sentence-transformers not installed; using BM25 only")
        return False
    return True


def embedding_model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def hybrid_rerank_pool() -> int:
    return max(10, int(os.getenv("HYBRID_RERANK_POOL", "50")))


def hybrid_vector_weight() -> float:
    return min(1.0, max(0.0, float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.65"))))


def hybrid_fallback_threshold() -> float:
    return min(1.0, max(0.0, float(os.getenv("HYBRID_FALLBACK_THRESHOLD", "0.55"))))


_model = None


def get_embedding_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        cache_dir = os.getenv("EMBEDDING_MODEL_CACHE", "").strip() or None
        logger.info("Loading embedding model: %s", embedding_model_name())
        _model = SentenceTransformer(embedding_model_name(), cache_folder=cache_dir)
    return _model


def embedding_text_for_event(event: EventItem) -> str:
    from .event_bm25 import event_document

    return event_document(event)


def text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def serialize_embedding(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def deserialize_embedding(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    array = np.frombuffer(blob, dtype=np.float32)
    if array.size == 0:
        return None
    return array


def encode_passages(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = get_embedding_model()
    return np.asarray(
        model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float32,
    )


def encode_query(text: str) -> np.ndarray:
    model = get_embedding_model()
    prompt_name = "query" if hasattr(model, "prompts") and "query" in getattr(model, "prompts", {}) else None
    if prompt_name:
        vector = model.encode([text], prompt_name="query", normalize_embeddings=True, show_progress_bar=False)
    else:
        vector = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vector[0], dtype=np.float32)


def cosine_scores(query_vector: np.ndarray, doc_matrix: np.ndarray) -> np.ndarray:
    if doc_matrix.size == 0:
        return np.zeros(0, dtype=np.float32)
    return doc_matrix @ query_vector


def load_embeddings_from_conn(
    conn: sqlite3.Connection,
    event_ids: list[str],
) -> dict[str, np.ndarray]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"SELECT event_id, embedding FROM events WHERE event_id IN ({placeholders}) AND embedding IS NOT NULL",
        event_ids,
    ).fetchall()
    result: dict[str, np.ndarray] = {}
    for row in rows:
        vector = deserialize_embedding(row["embedding"])
        if vector is not None:
            result[str(row["event_id"])] = vector
    return result


def update_event_embeddings(conn: sqlite3.Connection, events: list[EventItem]) -> int:
    if not hybrid_search_enabled() or not events:
        return 0

    model_name = embedding_model_name()
    pending: list[tuple[str, str, str]] = []
    for event in events:
        text = embedding_text_for_event(event)
        pending.append((event.event_id, text, text_hash(text)))

    existing: dict[str, tuple[str | None, str | None]] = {}
    ids = [item[0] for item in pending]
    placeholders = ", ".join("?" for _ in ids)
    for row in conn.execute(
        f"SELECT event_id, embedding_text_hash, embedding_model FROM events WHERE event_id IN ({placeholders})",
        ids,
    ).fetchall():
        existing[str(row["event_id"])] = (
            row["embedding_text_hash"],
            row["embedding_model"],
        )

    to_encode: list[tuple[str, str, str]] = []
    for event_id, text, digest in pending:
        old = existing.get(event_id)
        if old and old[0] == digest and old[1] == model_name:
            continue
        to_encode.append((event_id, text, digest))

    if not to_encode:
        return 0

    texts = [item[1] for item in to_encode]
    vectors = encode_passages(texts)
    rows = [
        (serialize_embedding(vectors[index]), digest, model_name, event_id)
        for index, (event_id, _text, digest) in enumerate(to_encode)
    ]
    conn.executemany(
        """
        UPDATE events
        SET embedding = ?, embedding_text_hash = ?, embedding_model = ?
        WHERE event_id = ?
        """,
        rows,
    )
    conn.commit()
    logger.info("Updated embeddings for %d events", len(rows))
    return len(rows)
