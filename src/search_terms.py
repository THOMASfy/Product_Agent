"""解析 @机器人 检索词：区分整句精确匹配 vs 多词 AND 匹配。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .query_expand import DOMAIN_EXPANSIONS

# 问句中常见虚词/动作词，不参与 AND 过滤
_QUERY_STOPWORDS = frozenset(
    {
        "的",
        "相关",
        "内容",
        "活动",
        "展会",
        "展會",
        "博览",
        "博覽",
        "展览",
        "展覽",
        "推送",
        "跟",
        "与",
        "及",
        "有什么",
        "有哪些",
        "请问",
        "查询",
        "搜索",
        "检索",
        "找",
        "看看",
        "一下",
        "关于",
        "有关",
        "一些",
        "几个",
        "什么",
        "好玩",
        "好玩的",
        "有趣",
        "值得去",
        "资讯",
        "資訊",
        "信息",
        "訊息",
        "消息",
        "新闻",
        "新聞",
        "动态",
        "動態",
        "报道",
        "報導",
        "下个月",
        "这个月",
        "本周",
        "下周",
        "吗",
        "呢",
        "呀",
        "啊",
    }
)

# 推荐/问句语气词：出现则从句中提取领域关键词，而非整句精确匹配
_INTENT_MARKERS = frozenset(
    {
        "请",
        "请你",
        "给我",
        "帮我",
        "帮忙",
        "推荐",
        "介绍",
        "有哪些",
        "有什么",
        "想要",
        "需要",
        "能否",
        "可以",
        "麻烦",
        "告诉我",
        "说说",
        "聊聊",
    }
)

# 口语浏览/打听（无「请/推荐」也能识别），如「大湾区有什么好玩的」
_COLLOQUIAL_MARKERS = frozenset(
    {
        "有啥",
        "哪儿",
        "哪里",
        "去哪",
        "去哪儿",
        "咋样",
        "怎么样",
        "好不好",
        "值得",
        "逛逛",
        "看看有什么",
        "有什么好",
        "有什么好玩",
    }
)

# 机构/专名标记：≥4 字中文仍走整词精确匹配（如「香港城市大学」）
_ENTITY_MARKERS = frozenset(
    {
        "大学",
        "学院",
        "学校",
        "公司",
        "企业",
        "集团",
        "研究院",
        "研究所",
        "中心",
    }
)

# 除 query_expand 外额外可识别的地点/主题词
_EXTRA_EMBEDDED_KEYWORDS = (
    "粤港澳大湾区",
    "粤港澳",
    "大湾區",
    "惠州",
    "中山",
    "江门",
    "肇庆",
    "北京",
    "上海",
    "杭州",
    "武汉",
    "成都",
    "青岛",
    "文化",
    "体育",
    "美食",
    "艺术",
    "音乐",
    "消费",
    "民生",
    "出海",
    "中小企业",
    "央企",
    "国企",
    "央企国企",
    "节庆",
    "盛事",
    "AI",
    "人工智能",
)


@dataclass(frozen=True)
class SearchTerms:
    """strict_phrase: 非空时要求活动文本包含该完整短语；filter_tokens: 多词 AND 匹配。"""

    strict_phrase: str
    filter_tokens: list[str]
    raw_query: str


def _strip_stopwords(text: str) -> list[str]:
    cleaned = text.lower()
    for word in sorted(_QUERY_STOPWORDS, key=len, reverse=True):
        cleaned = cleaned.replace(word, " ")
    parts = [p.strip() for p in re.split(r"[\s,，、/|+＋]+", cleaned) if p.strip()]
    return [p for p in parts if p not in _QUERY_STOPWORDS and len(p) >= 2]


def _is_recommendation_query(text: str) -> bool:
    return any(marker in text for marker in _INTENT_MARKERS)


def _is_colloquial_browse_query(text: str) -> bool:
    return any(marker in text for marker in _COLLOQUIAL_MARKERS)


def _is_nl_browse_query(text: str) -> bool:
    """自然语言「打听/推荐」类问句，非机构专名精确检索。"""
    return _is_recommendation_query(text) or _is_colloquial_browse_query(text)


@lru_cache(maxsize=1)
def _embedded_keyword_list() -> tuple[str, ...]:
    """与 query_expand 同步；长词优先匹配（如 粤港澳大湾区 先于 大湾区）。"""
    items: set[str] = set(_EXTRA_EMBEDDED_KEYWORDS)
    for key, aliases in DOMAIN_EXPANSIONS.items():
        items.add(key)
        for alias in aliases:
            if len(alias) >= 2 and re.search(r"[\u4e00-\u9fff]", alias):
                items.add(alias)
    return tuple(sorted(items, key=len, reverse=True))


def _is_entity_name(text: str) -> bool:
    return any(marker in text for marker in _ENTITY_MARKERS)


def _extract_embedded_keywords(text: str) -> list[str]:
    """从口语问句中提取 大湾区 / 香港 / 科技 等领域词。"""
    found: list[str] = []
    lower = text.lower()
    for key in _embedded_keyword_list():
        if key in text or key.lower() in lower:
            found.append(key)
    return list(dict.fromkeys(found))


def _resolve_embedded_search(text: str, embedded: list[str]) -> SearchTerms | None:
    """句中已识别领域词，且剩余部分仅为虚词/口语时，用领域词检索。"""
    if not embedded:
        return None
    if _is_nl_browse_query(text):
        return SearchTerms("", embedded, text)
    remainder = text
    for key in embedded:
        remainder = remainder.replace(key, " ")
    if not _strip_stopwords(remainder.lower()):
        return SearchTerms("", embedded, text)
    return None


def parse_search_terms(query: str) -> SearchTerms:
    raw = query.strip()
    text = raw.lower()
    if not text:
        return SearchTerms("", [], raw)

    parts = [p.strip() for p in re.split(r"[\s,，、/|+＋]+", text) if p.strip()]

    embedded = _extract_embedded_keywords(raw)
    resolved = _resolve_embedded_search(raw, embedded)
    if resolved is not None:
        return resolved

    # 自然语言推荐/问句：提取句中领域词，避免整句精确匹配导致 0 结果
    if _is_nl_browse_query(text):
        if embedded:
            return SearchTerms("", embedded, raw)
        meaningful = _strip_stopwords(text)
        if meaningful:
            return SearchTerms("", meaningful, raw)
        return SearchTerms("", [], raw)

    # 单个中文专名（≥4 字）：机构名等必须整词命中
    if (
        len(parts) == 1
        and len(parts[0]) >= 4
        and re.fullmatch(r"[\u4e00-\u9fff]+", parts[0])
    ):
        if _is_entity_name(parts[0]) or not _is_recommendation_query(text):
            return SearchTerms(parts[0], [parts[0]], raw)

    if len(parts) >= 2:
        tokens = [p for p in parts if p not in _QUERY_STOPWORDS and len(p) >= 2]
        if tokens:
            return SearchTerms("", tokens, raw)

    meaningful = _strip_stopwords(text)
    if meaningful:
        return SearchTerms("", meaningful, raw)

    if len(parts) == 1 and len(parts[0]) >= 2:
        return SearchTerms("", [parts[0]], raw)

    return SearchTerms("", [], raw)
