"""商机分析提示词构建：为 advise 模式生成结构化分析框架。"""

from __future__ import annotations

from datetime import date
from typing import Any

from .scraper.models import EventItem
from .theme_tags import get_event_themes, theme_label


def _summarize_events(events: list[EventItem]) -> dict[str, Any]:
    """从活动列表中提取结构化摘要，供分析参考。"""
    if not events:
        return {"total": 0}

    by_source: dict[str, int] = {}
    by_theme: dict[str, int] = {}
    by_topic: dict[str, int] = {}
    locations: set[str] = set()
    upcoming: list[dict[str, str]] = []

    for event in events:
        source = event.source or "unknown"
        by_source[source] = by_source.get(source, 0) + 1

        if event.topic:
            by_topic[event.topic] = by_topic.get(event.topic, 0) + 1

        for theme in get_event_themes(event):
            label = theme_label(theme)
            by_theme[label] = by_theme.get(label, 0) + 1

        if event.location:
            loc = event.location.strip()
            if loc:
                locations.add(loc[:20])

        upcoming.append(
            {
                "name": event.name[:80],
                "date": event.date_text or event.start_date or "",
                "source": source,
                "topic": event.topic or "",
                "location": (event.location or "")[:30],
            }
        )

    return {
        "total": len(events),
        "by_source": by_source,
        "by_theme": by_theme,
        "by_topic": by_topic,
        "locations": sorted(locations)[:10],
        "upcoming_list": upcoming,
    }


def build_analysis_instructions(
    *,
    user_context: str,
    events: list[EventItem],
    prior_query: str = "",
    prior_reply_preview: str = "",
) -> str:
    """生成精简的分析上下文（动态数据），静态框架由 Dify prompt 提供。

    控制在 500 字以内，避免超过 Dify 变量长度限制。
    """
    summary = _summarize_events(events)
    today_str = date.today().isoformat()

    themes_str = "、".join(list(summary.get("by_theme", {}).keys())[:5]) or "未识别"
    topics_str = "、".join(list(summary.get("by_topic", {}).keys())[:5]) or "综合"
    sources_str = "、".join(summary.get("by_source", {}).keys()) or "多来源"
    locations_str = ", ".join(summary.get("locations", [])[:5]) or "待定"

    # 上轮回复摘要限 150 字
    reply_brief = (prior_reply_preview or "无")[:150].replace("\n", " ")

    context = user_context.strip() or "（用户未补充公司方向，请根据检索关键词推断并给通用建议）"

    return (
        f"检索日期:{today_str}\n"
        f"用户背景:{context}\n"
        f"上轮检索:{prior_query.strip() or '未知'}\n"
        f"上轮回复摘要:{reply_brief}\n"
        f"活动总数:{summary.get('total', 0)}\n"
        f"数据来源:{sources_str}\n"
        f"涉及主题:{themes_str}\n"
        f"涉及方向:{topics_str}\n"
        f"涉及地区:{locations_str}"
    )


def build_analysis_meta(
    *,
    user_context: str,
    events: list[EventItem],
    prior_query: str = "",
    prior_reply_preview: str = "",
    search_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 advise 模式的增强 meta。"""
    base = dict(search_meta or {})
    base.update(
        {
            "analysis_instructions": build_analysis_instructions(
                user_context=user_context,
                events=events,
                prior_query=prior_query,
                prior_reply_preview=prior_reply_preview,
            ),
            "event_summary": _summarize_events(events),
            "prior_query": prior_query.strip(),
            "prior_reply_preview": (prior_reply_preview or "")[:500],
        }
    )
    return base


def build_local_analysis(
    *,
    user_context: str,
    events: list[EventItem],
    prior_query: str = "",
) -> str:
    """Dify 不可用时的本地结构化分析（降级版）。"""
    if not events:
        return "暂无可分析的活动数据，请先 @机器人 检索活动后再回复「分析」。"

    summary = _summarize_events(events)
    themes = summary.get("by_theme", {})
    topics = summary.get("by_topic", {})

    lines: list[str] = ["【商机分析报告（本地版）】", ""]

    # 1. 活动概览
    lines.append("一、活动概览")
    lines.append(f"共 {summary['total']} 条相关活动/资讯：")
    for source, count in summary.get("by_source", {}).items():
        source_label = {
            "scmp": "SCMP 新闻",
            "hktdc": "HKTDC 展会",
            "zhandaren": "展大人展会",
            "discoverhongkong": "香港活动",
        }.get(source, source)
        lines.append(f"  - {source_label}：{count} 条")
    if topics:
        lines.append(f"  方向分布：{', '.join(f'{k}({v})' for k, v in topics.items())}")
    if themes:
        lines.append(f"  主题分布：{', '.join(f'{k}({v})' for k, v in themes.items())}")
    lines.append("")

    # 2. 重点推荐
    top_events = events[:5]
    lines.append("二、重点推荐（前5条）")
    for i, event in enumerate(top_events, 1):
        topic_tag = f"[{event.topic}]" if event.topic else ""
        lines.append(f"  {i}. {event.name[:60]} {topic_tag}")
        lines.append(f"     时间：{event.date_text or event.start_date or '待定'}")
        if event.location:
            lines.append(f"     地点：{event.location[:40]}")
        if event.url:
            lines.append(f"     链接：{event.url}")
    lines.append("")

    # 3. 用户背景 + 通用建议
    lines.append("三、参展建议")
    if user_context.strip():
        lines.append(f"用户背景：{user_context.strip()[:200]}")
    lines.append("建议优先关注与自身业务方向匹配度最高的活动，提前报名并准备对接材料。")
    lines.append("")

    # 4. 行动清单
    lines.append("四、行动清单")
    for i, event in enumerate(top_events[:3], 1):
        action = f"  {i}. 【高】关注「{event.name[:40]}」"
        if event.start_date:
            action += f"（{event.start_date}前确认参与）"
        lines.append(action)
    lines.append(f"  {len(top_events[:3]) + 1}. 【中】根据活动方向准备企业介绍材料")
    lines.append(f"  {len(top_events[:3]) + 2}. 【低】持续关注机器人推送的最新活动动态")
    lines.append("")
    lines.append("💡 此为本地分析，配置 Dify Workflow 后可获得更智能的 AI 深度分析。")

    return "\n".join(lines)
