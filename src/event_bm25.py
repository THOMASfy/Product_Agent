"""活动检索：jieba 分词 + BM25 相关性排序。"""

from __future__ import annotations

import re
from dataclasses import dataclass

import jieba
from rank_bm25 import BM25Okapi

from .query_expand import DOMAIN_EXPANSIONS, expand_query_tokens
from .scraper.models import EventItem
from .search_terms import SearchTerms
from .theme_tags import (
    detect_query_themes,
    event_has_theme,
    resolve_theme_token,
    sort_events_by_themes,
    theme_match_score,
)

# 领域词加入 jieba 词典，避免「大湾区」等被错误切分
for _key in DOMAIN_EXPANSIONS:
    jieba.add_word(_key, freq=10000)


def tokenize_text(text: str) -> list[str]:
    text = text.strip().lower()
    if not text:
        return []
    tokens: list[str] = []
    for word in jieba.cut_for_search(text):
        word = word.strip().lower()
        if len(word) < 2 and not re.fullmatch(r"[a-z0-9]{2,}", word):
            continue
        if word:
            tokens.append(word)
    return tokens


def _dedupe(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def event_document(event: EventItem) -> str:
    """标题重复加权，提升名称字段在 BM25 中的权重。"""
    parts = [event.name, event.name, event.name]
    parts.extend(
        [
            event.description,
            event.organizer,
            event.location,
            event.date_text,
            event.source,
            event.topic,
        ]
    )
    return " ".join(p for p in parts if p)


def prepare_query_tokens(terms: SearchTerms, raw_query: str) -> list[str]:
    pieces: list[str] = []
    if terms.strict_phrase:
        pieces.append(terms.strict_phrase)
    elif terms.filter_tokens:
        pieces.extend(expand_query_tokens(terms.filter_tokens, raw_query=raw_query))

    tokens: list[str] = []
    for piece in pieces:
        tokens.extend(tokenize_text(piece))
    return _dedupe(tokens)


def _expanded_token_set(token: str, *, raw_query: str) -> set[str]:
    aliases = expand_query_tokens([token], raw_query=raw_query)
    result: set[str] = set()
    for alias in aliases:
        result.update(tokenize_text(alias))
        norm = alias.strip().lower()
        if norm:
            result.add(norm)
    return result


def matches_filter_groups(
    doc_tokens: set[str],
    filter_tokens: list[str],
    *,
    raw_query: str,
    event: EventItem | None = None,
) -> bool:
    """每个 filter 词及其领域扩展别名至少命中一个（OR）；多个词之间 AND。"""
    for token in filter_tokens:
        theme = resolve_theme_token(token, raw_query=raw_query)
        if theme and event is not None:
            if not event_has_theme(event, theme):
                return False
            continue
        candidates = _expanded_token_set(token, raw_query=raw_query)
        if not doc_tokens.intersection(candidates):
            return False
    return True


def matches_any_filter_group(
    doc_tokens: set[str],
    filter_tokens: list[str],
    *,
    raw_query: str,
    event: EventItem | None = None,
) -> bool:
    """至少一个 filter 词命中（OR，用于 AND 无结果时降级）。"""
    for token in filter_tokens:
        theme = resolve_theme_token(token, raw_query=raw_query)
        if theme and event is not None:
            if event_has_theme(event, theme):
                return True
            continue
        candidates = _expanded_token_set(token, raw_query=raw_query)
        if doc_tokens.intersection(candidates):
            return True
    return False


@dataclass(frozen=True)
class RankResult:
    events: list[EventItem]
    match_mode: str  # and | or_relaxed | phrase | bm25 | none


def rank_events_by_bm25(
    events: list[EventItem],
    *,
    query_tokens: list[str],
    strict_phrase: str = "",
    filter_tokens: list[str] | None = None,
    raw_query: str = "",
    limit: int = 10,
) -> RankResult:
    if not events:
        return RankResult([], "none")

    filter_tokens = filter_tokens or []
    query_themes = detect_query_themes(filter_tokens, raw_query)
    indexed: list[tuple[EventItem, list[str], set[str], str]] = []

    for event in events:
        doc_text = event_document(event)
        doc_tokens_list = tokenize_text(doc_text)
        indexed.append(
            (
                event,
                doc_tokens_list,
                set(doc_tokens_list),
                doc_text.lower(),
            )
        )

    candidates = list(range(len(indexed)))

    if strict_phrase:
        phrase = strict_phrase.lower()
        candidates = [i for i in candidates if phrase in indexed[i][3]]

    if filter_tokens:
        and_candidates = [
            i
            for i in candidates
            if matches_filter_groups(
                indexed[i][2],
                filter_tokens,
                raw_query=raw_query,
                event=indexed[i][0],
            )
        ]
        if and_candidates:
            candidates = and_candidates
            match_mode = "and"
        elif len(filter_tokens) > 1:
            candidates = [
                i
                for i in candidates
                if matches_any_filter_group(
                    indexed[i][2],
                    filter_tokens,
                    raw_query=raw_query,
                    event=indexed[i][0],
                )
            ]
            match_mode = "or_relaxed"
        else:
            candidates = and_candidates
            match_mode = "and"
    else:
        match_mode = "phrase" if strict_phrase else "bm25"

    if not candidates:
        return RankResult([], "none")

    if not query_tokens:
        result = [indexed[i][0] for i in candidates]
        result.sort(key=lambda e: (e.start_date or "9999", e.name))
        return RankResult(result[:limit], match_mode)

    sub_corpus = [indexed[i][1] for i in candidates]
    bm25 = BM25Okapi(sub_corpus)
    scores = bm25.get_scores(query_tokens)

    scored: list[tuple[float, EventItem]] = []
    for rank, doc_idx in enumerate(candidates):
        event = indexed[doc_idx][0]
        score = float(scores[rank])
        score += theme_match_score(event, query_themes)
        if score > 0 or filter_tokens or strict_phrase:
            scored.append((score, event))

    if not scored:
        return RankResult([], "none")

    scored.sort(key=lambda item: (-item[0], item[1].start_date or "9999", item[1].name))
    ranked = [event for _, event in scored[:limit]]
    return RankResult(sort_events_by_themes(ranked, query_themes), match_mode)
