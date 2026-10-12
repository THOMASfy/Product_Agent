"""将活动列表格式化为飞书消息。"""

from __future__ import annotations

import re
from typing import Any

from .models import EventItem
from .location_format import format_event_location


def _event_period(event: EventItem) -> str:
    return event.date_text or event.start_date or "待定"


def _sanitize_brackets(text: str) -> str:
    """避免活动名称中的方括号破坏 Markdown 链接语法。"""
    return text.replace("[", "（").replace("]", "）")


def _event_line_label(index: int, event: EventItem) -> str:
    return f"{index}. {_sanitize_brackets(event.name)}"


def _event_location(event: EventItem) -> str:
    return format_event_location(event)


def _event_domain(event: EventItem) -> str:
    from ..theme_tags import event_has_theme, theme_label
    from .scmp_topics import classify_scmp_event

    if event.source == "scmp":
        topic = event.topic or classify_scmp_event(event)
        if topic:
            if topic == "科技" and event_has_theme(event, "AI"):
                return theme_label("AI")
            return f"新闻 / {topic}"
        return "新闻 / 资讯"

    if event_has_theme(event, "AI"):
        return theme_label("AI")

    text = f"{event.name} {event.description} {event.organizer}".lower()
    if any(keyword in text for keyword in ["养老", "老龄", "長者", "长者", "健康", "醫療", "医疗", "银发", "銀髮"]):
        return "养老 / 大健康"
    if any(
        keyword in text
        for keyword in [
            "电子",
            "電子",
            "通信",
            "通訊",
            "科技",
            "科创",
            "科創",
            "数据中心",
            "光电",
            "電腦",
            "电脑",
        ]
    ):
        return "电子 / 通信 / 科技"
    if any(keyword in text for keyword in ["教育", "人才", "青年", "学术", "學術", "書展", "书展"]):
        return "教育 / 人才"
    if any(keyword in text for keyword in ["民生", "惠民", "消费", "消費", "美食博覽", "美食博览", "政府"]):
        return "惠民 / 大型民生"
    if any(keyword in text for keyword in ["龍舟", "龙舟", "中秋", "盛事", "節日", "节日", "峰會", "峰会"]):
        return "香港级 / 国际大型活动"
    if event.source == "zhandaren":
        return "展会 / 商机"
    return "香港级 / 国际大型活动"


def _event_meta(event: EventItem) -> str:
    return f"({_event_period(event)} {_event_location(event)} {_event_domain(event)})"


def _extract_description_intro(description: str, event: EventItem) -> str:
    text = re.sub(r"\s+", " ", description or "").strip()
    if " 行业：" in text:
        text = text.split(" 行业：", 1)[0].strip()
    name = (event.name or "").strip()
    if text and name and text == name:
        return ""
    return text


def _hktdc_meta_fallback(description: str, *, max_len: int = 100) -> str:
    if " 行业：" not in description:
        return ""
    tail = description.split(" 行业：", 1)[1]
    industry = tail.split(" 形式：", 1)[0].strip()
    fmt_part = ""
    if " 形式：" in tail:
        fmt_part = tail.split(" 形式：", 1)[1].split(" 含线上", 1)[0].strip()
    parts: list[str] = []
    if industry:
        if len(industry) > max_len:
            industry = industry[: max_len - 3].rstrip("、,") + "..."
        parts.append(f"主打行业：{industry}")
    if fmt_part:
        parts.append(f"形式：{fmt_part}")
    return "，".join(parts)


def _intro_is_weak(intro: str, event: EventItem) -> bool:
    intro_norm = intro.strip().lower()
    if not intro_norm:
        return True
    name = (event.name or "").strip().lower()
    if intro_norm == name:
        return True
    if len(intro_norm) < 45 and name and (intro_norm in name or name in intro_norm):
        return True
    if event.source != "hktdc":
        return False
    if "。" in intro or "." in intro:
        return False
    if len(intro_norm) < 55:
        return True
    if re.search(r"\b20\d{2}\b", intro) and len(intro_norm) < 75:
        return True
    return False


def _truncate_blurb(text: str, max_len: int = 120) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    for sep in ["。", "！", "？", ". ", "! ", "? ", "，", ", "]:
        idx = cut.rfind(sep)
        if idx >= max_len // 2:
            return cut[: idx + len(sep)].strip()
    return cut.rstrip() + "..."


def _event_summary(event: EventItem) -> str:
    raw_desc = event.description or ""
    intro = _extract_description_intro(raw_desc, event)

    if not intro or intro in {
        "（详见活动页面）",
        "（详见 HKTDC 活动页面）",
        "（暂无简介）",
    }:
        intro = _hktdc_meta_fallback(raw_desc)

    if _intro_is_weak(intro, event):
        intro = _hktdc_meta_fallback(raw_desc) or intro

    if not intro:
        intro = event.organizer or ""

    intro = _remove_boilerplate(intro)
    summary = _complete_sentences(intro, max_sentences=2)
    if not summary:
        summary = _truncate_blurb(intro, 120)

    if len(summary) > 140:
        summary = (
            _complete_sentences(summary[:200], max_sentences=2)
            or _truncate_blurb(summary, 140)
        )
    return summary or "详情请查看活动主页。"


def _remove_boilerplate(text: str) -> str:
    patterns = [
        r"圖片由[^。！？!?；;]*提供[。！？!?；;]?",
        r"图片由[^。！？!?；;]*提供[。！？!?；;]?",
        r"資料由[^。！？!?；;]*提供[。！？!?；;]?",
        r"资料由[^。！？!?；;]*提供[。！？!?；;]?",
        r"相片由[^。！？!?；;]*提供[。！？!?；;]?",
        r"照片由[^。！？!?；;]*提供[。！？!?；;]?",
        r"圖像由[^。！？!?；;]*提供[。！？!?；;]?",
        r"图像由[^。！？!?；;]*提供[。！？!?；;]?",
        r"以上圖片[^。！？!?；;]*[。！？!?；;]?",
        r"以上图片[^。！？!?；;]*[。！？!?；;]?",
        r"資料來源[:：][^。！？!?；;]*[。！？!?；;]?",
        r"资料来源[:：][^。！？!?；;]*[。！？!?；;]?",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()


def _complete_sentences(text: str, *, max_sentences: int) -> str:
    text = text.strip()
    if not text:
        return ""

    sentence_marks = {"。", "！", "？", "!", "?", "；", ";"}
    sentences: list[str] = []
    current: list[str] = []
    for char in text:
        current.append(char)
        if char in sentence_marks:
            sentence = "".join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []
            if len(sentences) >= max_sentences:
                break

    if sentences:
        return "".join(sentences).strip()

    # No sentence ending exists: keep the whole short phrase rather than cutting mid-word.
    return text if len(text) <= 80 else ""


def format_events_post(
    events: list[EventItem],
    *,
    header: str = "【香港活动日历】",
    empty_text: str = "今日暂无新活动。",
    footer_link: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构造飞书 post 富文本消息体，每条活动为可点击超链接。"""
    if not events:
        body: dict[str, Any] = {
            "zh_cn": {
                "title": header,
                "content": [[{"tag": "text", "text": empty_text}]],
            }
        }
        _append_footer_link(body, footer_link)
        return body

    content: list[list[dict[str, str]]] = []
    for index, event in enumerate(events, start=1):
        label = _event_line_label(index, event)
        if event.url:
            content.append([{"tag": "a", "text": label, "href": event.url}])
        else:
            content.append([{"tag": "text", "text": label}])
        content.append([{"tag": "text", "text": _event_meta(event)}])
        content.append([{"tag": "text", "text": _event_summary(event)}])

    body = {"zh_cn": {"title": header, "content": content}}
    _append_footer_link(body, footer_link)
    return body


def _footer_markdown_line(text: str, url: str, *, emphasis: str = "heading") -> str:
    link = f"[{text}]({url})"
    if emphasis == "heading":
        return f"### {link}"
    if emphasis == "bold":
        return f"**{link}**"
    return link


def _append_footer_link(body: dict[str, Any], footer_link: dict[str, str] | None) -> None:
    if not footer_link:
        return
    url = str(footer_link.get("url") or "").strip()
    if not url.startswith("http"):
        return
    text = str(footer_link.get("text") or "打开多维表格").strip() or "打开多维表格"
    emphasis = str(footer_link.get("emphasis") or "heading").strip().lower()
    zh = body.setdefault("zh_cn", {})
    content = zh.setdefault("content", [])
    if content:
        content.append([{"tag": "hr"}])
    content.append(
        [{"tag": "md", "text": _footer_markdown_line(text, url, emphasis=emphasis)}]
    )


def format_events_preview(
    events: list[EventItem],
    *,
    header: str = "【香港活动日历】",
    empty_text: str = "今日暂无新活动。",
    query_themes: list[str] | None = None,
) -> str:
    """CLI 预览用纯文本，格式与群消息一致。"""
    if not events:
        return empty_text

    from ..theme_tags import partition_events_by_primary_theme, theme_label

    query_themes = query_themes or []
    lines = [header, ""]

    sections: list[tuple[str, list[EventItem]]]
    if query_themes:
        primary = query_themes[0]
        matched, rest = partition_events_by_primary_theme(events, primary)
        sections = []
        if matched:
            sections.append((f"【{theme_label(primary)} 相关优先】", matched))
        if rest:
            sections.append(("【其他相关活动】", rest))
        if not sections:
            sections = [(header, events)]
    else:
        sections = [("", events)]

    for section_index, (section_header, section_events) in enumerate(sections):
        if section_header:
            if section_index > 0:
                lines.append("")
            lines.append(section_header)
            lines.append("")
        for index, event in enumerate(section_events, start=1):
            domain = _event_domain(event)
            lines.append(f"🎯 {_sanitize_brackets(event.name)}")
            lines.append(f"📅 {_event_period(event)}")
            lines.append(f"📍 {_event_location(event)}")
            if domain:
                lines.append(f"🏷 {domain}")
            summary = _event_summary(event)
            if summary:
                lines.append(summary)
            if event.url:
                lines.append(event.url)
            if index < len(section_events):
                lines.append("")

    return "\n".join(lines).strip()
