"""SCMP 主题分桶：分主题搜索、匹配与财经类排除。"""

from __future__ import annotations

from dataclasses import dataclass

from ..theme_tags import event_has_theme
from .models import EventItem

# 至少命中一项，确保与内地/香港/大湾区相关
REGION_ANCHORS: tuple[str, ...] = (
    "hong kong",
    "hk",
    "china",
    "chinese",
    "mainland",
    "greater bay",
    "bay area",
    "guangdong",
    "shenzhen",
    "guangzhou",
    "macau",
    "大湾区",
    "香港",
    "内地",
    "粤",
    "深港",
    "港澳",
)

# 命中任一则整篇丢弃（财经/商业报道）
FINANCE_EXCLUDE: tuple[str, ...] = (
    "finance",
    "financial",
    "stock market",
    "stock price",
    "stocks",
    "equity market",
    "bond market",
    "forex",
    "currency trader",
    "cryptocurrency",
    "crypto",
    "bitcoin",
    "banking sector",
    "central bank",
    "interest rate",
    "monetary policy",
    "earnings report",
    "quarterly earnings",
    "revenue beat",
    "profit warning",
    "dividend",
    "ipo",
    "merger deal",
    "acquisition deal",
    "hedge fund",
    "private equity",
    "wall street",
    "hang seng index",
    "hsi ",
    "market rally",
    "bear market",
    "bull market",
    "trading floor",
    "金融",
    "财经",
    "股市",
    "股票",
    "证券",
    "债券",
    "基金",
    "投行",
    "财报",
    "盈利",
    "营收",
    "汇率",
    "央行",
    "加息",
    "降息",
    "上市融资",
    "并购",
    "对冲基金",
    "私募股权",
    "恒生指数",
    "沪指",
    "深指",
)


@dataclass(frozen=True)
class ScmpTopic:
    id: str
    label: str
    queries: tuple[str, ...]
    keywords: tuple[str, ...]


# 顺序即推送优先级（靠前优先）
SCMP_TOPICS: tuple[ScmpTopic, ...] = (
    ScmpTopic(
        id="tech",
        label="科技",
        queries=(
            "technology innovation Hong Kong China",
            "artificial intelligence AI Hong Kong China",
        ),
        keywords=(
            "technology",
            "tech",
            "innovation",
            "artificial intelligence",
            " ai ",
            "machine learning",
            "semiconductor",
            "chip",
            "startup",
            "digital",
            "smart city",
            "科技",
            "创新",
            "人工智能",
            "半导体",
            "芯片",
            "数字化",
            "科创",
        ),
    ),
    ScmpTopic(
        id="go_global",
        label="出海",
        queries=(
            "China overseas expansion export Hong Kong",
            "go global international market Chinese companies",
        ),
        keywords=(
            "go global",
            "overseas",
            "export",
            "international market",
            "international expansion",
            "belt and road",
            "globalisation",
            "globalization",
            "出海",
            "走出去",
            "出口",
            "国际化",
            "一带一路",
        ),
    ),
    ScmpTopic(
        id="mainland_hk",
        label="内地香港",
        queries=(
            "Greater Bay Area Hong Kong mainland China",
            "cross-border Hong Kong Shenzhen Guangdong",
        ),
        keywords=(
            "greater bay",
            "bay area",
            "mainland",
            "cross-border",
            "hong kong",
            "shenzhen",
            "guangdong",
            "guangzhou",
            "macau",
            "大湾区",
            "跨境",
            "内地",
            "港澳",
            "深港",
            "粤港",
        ),
    ),
    ScmpTopic(
        id="sme",
        label="中小企业",
        queries=(
            "SME small business Hong Kong China",
            "small medium enterprise startup Hong Kong",
        ),
        keywords=(
            "sme",
            "small business",
            "small and medium",
            "medium enterprise",
            "entrepreneur",
            "startup",
            "中小企业",
            "中小企",
            "小微",
            "创业",
        ),
    ),
    ScmpTopic(
        id="soe",
        label="央企国企",
        queries=(
            "state-owned enterprise China Hong Kong",
            "central SOE state firm China reform",
        ),
        keywords=(
            "state-owned",
            "state owned",
            "soe",
            "central enterprise",
            "state firm",
            "state asset",
            "央企",
            "国企",
            "国有",
            "国资委",
        ),
    ),
    ScmpTopic(
        id="education",
        label="教育",
        queries=(
            "education university school Hong Kong China",
            "talent training Hong Kong Greater Bay Area",
        ),
        keywords=(
            "education",
            "university",
            "school",
            "student",
            "academic",
            "talent",
            "vocational",
            "教育",
            "大学",
            "高校",
            "学校",
            "人才",
            "培训",
            "学术",
        ),
    ),
    ScmpTopic(
        id="livelihood",
        label="民生",
        queries=(
            "livelihood housing welfare Hong Kong",
            "public services healthcare community Hong Kong China",
        ),
        keywords=(
            "livelihood",
            "housing",
            "welfare",
            "public service",
            "healthcare",
            "community",
            "elderly care",
            "social policy",
            "民生",
            "住房",
            "医疗",
            "养老",
            "社区",
            "惠民",
            "公共服务",
        ),
    ),
)

_TOPIC_BY_ID = {topic.id: topic for topic in SCMP_TOPICS}
_TOPIC_PRIORITY = {topic.id: index for index, topic in enumerate(SCMP_TOPICS)}


def _normalize(text: str) -> str:
    return f" {text.casefold()} "


def _matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(keyword.casefold() in normalized for keyword in keywords if keyword)


def is_finance_article(text: str) -> bool:
    return _matches_any(text, FINANCE_EXCLUDE)


def has_region_anchor(text: str) -> bool:
    return _matches_any(text, REGION_ANCHORS)


def classify_scmp_text(text: str) -> str | None:
    """返回命中的最高优先级主题 label；不匹配或财经类返回 None。"""
    if not text.strip() or is_finance_article(text):
        return None
    if not has_region_anchor(text):
        return None

    if event_has_theme(
        EventItem(
            event_id="tmp",
            name=text,
            date_text="",
            start_date="",
            end_date="",
            organizer="",
            description="",
            location="",
            url="",
            source="scmp",
        ),
        "AI",
    ):
        return "科技"

    for topic in SCMP_TOPICS:
        if _matches_any(text, topic.keywords):
            return topic.label
    return None


def classify_scmp_event(event: EventItem) -> str | None:
    if event.topic:
        return event.topic
    text = f"{event.name} {event.description}"
    return classify_scmp_text(text)


def scmp_topic_priority(label: str | None) -> int:
    if not label:
        return len(SCMP_TOPICS)
    for topic in SCMP_TOPICS:
        if topic.label == label or topic.id == label:
            return _TOPIC_PRIORITY[topic.id]
    return len(SCMP_TOPICS)


def topic_matches_raw_article(*, headline: str, summary: str, topic: ScmpTopic) -> bool:
    combined = f"{headline} {summary}"
    if is_finance_article(combined):
        return False
    if not has_region_anchor(combined):
        return False
    if _matches_any(combined, topic.keywords):
        return True
    if topic.id == "tech" and event_has_theme(
        EventItem(
            event_id="tmp",
            name=headline,
            date_text="",
            start_date="",
            end_date="",
            organizer="",
            description=summary,
            location="",
            url="",
            source="scmp",
        ),
        "AI",
    ):
        return True
    return False
