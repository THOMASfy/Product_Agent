"""Hybrid 检索：BM25 硬过滤 + 向量 rerank / fallback。"""

from __future__ import annotations

import numpy as np

from .embedding_service import (
    cosine_scores,
    encode_query,
    hybrid_fallback_threshold,
    hybrid_rerank_pool,
    hybrid_search_enabled,
    hybrid_vector_weight,
)
from .event_bm25 import RankResult, rank_events_by_bm25
from .scraper.models import EventItem
from .search_terms import SearchTerms
from .theme_tags import sort_events_by_themes, detect_query_themes


def _normalize_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    arr = np.asarray(values, dtype=np.float32)
    min_val = float(arr.min())
    max_val = float(arr.max())
    if max_val <= min_val:
        return [1.0 for _ in values]
    scaled = (arr - min_val) / (max_val - min_val)
    return [float(x) for x in scaled]


def _combine_scores(
    events: list[EventItem],
    *,
    bm25_scores: dict[str, float],
    vector_scores: dict[str, float],
) -> list[tuple[float, EventItem]]:
    alpha = hybrid_vector_weight()
    bm25_norm = _normalize_scores([bm25_scores.get(event.event_id, 0.0) for event in events])
    vector_norm = _normalize_scores([vector_scores.get(event.event_id, 0.0) for event in events])
    combined: list[tuple[float, EventItem]] = []
    for index, event in enumerate(events):
        score = alpha * vector_norm[index] + (1.0 - alpha) * bm25_norm[index]
        combined.append((score, event))
    combined.sort(key=lambda item: (-item[0], item[1].start_date or "9999", item[1].name))
    return combined


def _vector_rerank(
    events: list[EventItem],
    *,
    query: str,
    embeddings: dict[str, np.ndarray],
    bm25_scores: dict[str, float],
    query_themes: list[str],
    limit: int,
) -> list[EventItem]:
    query_vector = encode_query(query.strip())
    vector_scores: dict[str, float] = {}
    for event in events:
        vector = embeddings.get(event.event_id)
        if vector is None:
            continue
        vector_scores[event.event_id] = float(cosine_scores(query_vector, vector.reshape(1, -1))[0])

    if not vector_scores:
        return events[:limit]

    ranked = _combine_scores(events, bm25_scores=bm25_scores, vector_scores=vector_scores)
    result = [event for _score, event in ranked[:limit]]
    return sort_events_by_themes(result, query_themes)


def _vector_fallback(
    events: list[EventItem],
    *,
    query: str,
    embeddings: dict[str, np.ndarray],
    limit: int,
    query_themes: list[str],
) -> list[EventItem]:
    query_vector = encode_query(query.strip())
    threshold = hybrid_fallback_threshold()
    scored: list[tuple[float, EventItem]] = []
    for event in events:
        vector = embeddings.get(event.event_id)
        if vector is None:
            continue
        score = float(cosine_scores(query_vector, vector.reshape(1, -1))[0])
        if score >= threshold:
            scored.append((score, event))
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], item[1].start_date or "9999", item[1].name))
    result = [event for _score, event in scored[:limit]]
    return sort_events_by_themes(result, query_themes)


def _bm25_score_map(
    events: list[EventItem],
    *,
    query_tokens: list[str],
    strict_phrase: str,
    filter_tokens: list[str],
    raw_query: str,
) -> dict[str, float]:
    pool = hybrid_rerank_pool()
    ranked = rank_events_by_bm25(
        events,
        query_tokens=query_tokens,
        strict_phrase=strict_phrase,
        filter_tokens=filter_tokens,
        raw_query=raw_query,
        limit=pool,
    )
    if not ranked.events:
        return {}
    # Re-run scoring only for ordering reference: use rank position as proxy if needed
    scores: dict[str, float] = {}
    total = len(ranked.events)
    for index, event in enumerate(ranked.events):
        scores[event.event_id] = float(total - index)
    return scores


def hybrid_rank(
    events: list[EventItem],
    *,
    query: str,
    terms: SearchTerms,
    query_tokens: list[str],
    embeddings: dict[str, np.ndarray],
    limit: int = 10,
) -> RankResult:
    pool = hybrid_rerank_pool() if hybrid_search_enabled() else limit
    bm25_result = rank_events_by_bm25(
        events,
        query_tokens=query_tokens,
        strict_phrase=terms.strict_phrase,
        filter_tokens=terms.filter_tokens,
        raw_query=query,
        limit=pool,
    )

    if not hybrid_search_enabled() or not query.strip():
        return RankResult(bm25_result.events[:limit], bm25_result.match_mode)

    query_themes = detect_query_themes(terms.filter_tokens, query)
    bm25_scores = _bm25_score_map(
        events,
        query_tokens=query_tokens,
        strict_phrase=terms.strict_phrase,
        filter_tokens=terms.filter_tokens,
        raw_query=query,
    )

    if bm25_result.events:
        reranked = _vector_rerank(
            bm25_result.events,
            query=query,
            embeddings=embeddings,
            bm25_scores=bm25_scores,
            query_themes=query_themes,
            limit=limit,
        )
        mode = bm25_result.match_mode
        if mode not in {"none"} and reranked != bm25_result.events[:limit]:
            mode = f"{mode}_rerank"
        return RankResult(reranked, mode)

    if terms.strict_phrase:
        return RankResult([], "none")

    fallback = _vector_fallback(
        events,
        query=query,
        embeddings=embeddings,
        limit=limit,
        query_themes=query_themes,
    )
    if fallback:
        return RankResult(fallback, "vector_fallback")

    return RankResult([], "none")
