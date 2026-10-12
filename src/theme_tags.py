"""活动主题标签：识别 AI 等主题，用于检索加权与结果分组。"""

from __future__ import annotations

import re

from .query_expand import DOMAIN_EXPANSIONS
from .scraper.models import EventItem

# 与 DOMAIN_EXPANSIONS 的 key 对齐；用于查询意图与活动打标
THEME_KEYS: tuple[str, ...] = ("AI", "科技", "养老", "教育", "展会", "香港", "HKTDC", "大湾区")

# 活动文本命中 AI 主题（比 BM25 分词更严格，避免 fair / email 等误伤）
_AI_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bai\b",
        r"\ba\.?i\.?\b",
        r"人工智能",
        r"智能体",
        r"大模型",
        r"生成式",
        r"aigc",
        r"\bllm\b",
        r"机器学习",
        r"機器學習",
        r"深度学习",
        r"深度學習",
        r"ai[-\s]?enabled",
        r"ai[-\s]?powered",
        r"chatgpt",
        r"生成式人工智能",
    )
)

_THEME_LABELS: dict[str, str] = {
    "AI": "AI / 人工智能",
    "科技": "科技 / 信息技术",
    "养老": "养老 / 大健康",
    "教育": "教育 / 书展",
    "展会": "展会 / 博览",
    "香港": "香港",
    "HKTDC": "HKTDC / 贸发局",
    "大湾区": "大湾区",
}


def theme_label(theme: str) -> str:
    return _THEME_LABELS.get(theme, theme)


def _theme_terms(theme: str) -> set[str]:
    terms: set[str] = {theme.lower()}
    for alias in DOMAIN_EXPANSIONS.get(theme, []):
        terms.add(alias.lower())
    return terms


def resolve_theme_token(token: str, *, raw_query: str = "") -> str | None:
    """若 token 属于某主题域，返回主题 key。"""
    norm = token.strip().lower()
    if not norm:
        return None
    for theme in THEME_KEYS:
        if norm in _theme_terms(theme):
            return theme
    return None


def detect_query_themes(filter_tokens: list[str], raw_query: str = "") -> list[str]:
    """从 filter tokens 与原始问句识别用户关心的主题（去重保序）。"""
    found: list[str] = []
    seen: set[str] = set()
    rq = raw_query.strip().lower()
    token_set = {t.strip().lower() for t in filter_tokens if t.strip()}

    for theme in THEME_KEYS:
        terms = _theme_terms(theme)
        hit = bool(token_set.intersection(terms))
        if not hit and rq:
            for term in sorted(terms, key=len, reverse=True):
                if len(term) >= 2 and term in rq:
                    hit = True
                    break
        if hit and theme not in seen:
            seen.add(theme)
            found.append(theme)
    return found


def event_has_theme(event: EventItem, theme: str) -> bool:
    text = " ".join(
        p
        for p in (
            event.name,
            event.description,
            event.organizer,
            event.location,
            event.date_text,
        )
        if p
    )
    if not text:
        return False

    if theme == "AI":
        lower = text.lower()
        return any(p.search(lower) or p.search(text) for p in _AI_TEXT_PATTERNS)

    lower = text.lower()
    return any(term in lower or term in text for term in _theme_terms(theme) if len(term) >= 2)


def get_event_themes(event: EventItem) -> set[str]:
    return {theme for theme in THEME_KEYS if event_has_theme(event, theme)}


def theme_match_score(event: EventItem, query_themes: list[str]) -> float:
    """查询主题与活动主题重合越多，加分越高；组合主题额外奖励。"""
    if not query_themes:
        return 0.0
    event_themes = get_event_themes(event)
    matched = [theme for theme in query_themes if theme in event_themes]
    if not matched:
        return 0.0
    score = float(len(matched)) * 4.0
    if len(query_themes) > 1 and len(matched) == len(query_themes):
        score += 6.0
    if "AI" in matched:
        score += 2.0
    return score


def sort_events_by_themes(
    events: list[EventItem],
    query_themes: list[str],
) -> list[EventItem]:
    """在 BM25 已排序结果上，按主题相关度二次排序并分组（主题命中优先）。"""
    if not events or not query_themes:
        return events

    primary = query_themes[0]

    def sort_key(event: EventItem) -> tuple[int, int, float, str, str]:
        themes = get_event_themes(event)
        primary_hit = 0 if primary in themes else 1
        all_hit = 0 if all(t in themes for t in query_themes) else 1
        bonus = -theme_match_score(event, query_themes)
        return (primary_hit, all_hit, bonus, event.start_date or "9999", event.name)

    return sorted(events, key=sort_key)


def partition_events_by_primary_theme(
    events: list[EventItem],
    primary_theme: str,
) -> tuple[list[EventItem], list[EventItem]]:
    """拆成「主主题命中」与「其余」两组，便于分段展示。"""
    if not primary_theme:
        return events, []
    matched: list[EventItem] = []
    rest: list[EventItem] = []
    for event in events:
        if event_has_theme(event, primary_theme):
            matched.append(event)
        else:
            rest.append(event)
    return matched, rest
