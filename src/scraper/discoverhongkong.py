"""Discover Hong Kong 活动页抓取（内嵌 JSON）。"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from html import unescape

import cloudscraper

from .filters import parse_start_date, start_date_in_window
from .models import EventItem

logger = logging.getLogger(__name__)

EVENTS_URL = "https://www.discoverhongkong.com/tc/events.html"
DEFAULT_EXCLUDE = ["慈善籌款", "捐米款", "一般慈善"]
HK_INCLUDE_KEYWORDS = [
    # 养老 / 大健康
    "醫療",
    "医疗",
    "健康",
    "大健康",
    "長者",
    "长者",
    "銀髮",
    "银发",
    "福利",
    "民生",
    # 电子 / 通信 / 科技
    "科技",
    "科創",
    "科创",
    "創新科技",
    "创新科技",
    "資訊科技",
    "信息科技",
    "IT",
    "電子",
    "电子",
    "數碼",
    "数码",
    "智能",
    "數字經濟",
    "数字经济",
    "數字化",
    "数字化",
    "人工智能",
    "AI",
    "通信",
    "通訊",
    "5G",
    "網絡",
    "网络",
    "電訊",
    "电讯",
    "數據中心",
    "数据中心",
    "峰會",
    "峰会",
    "博覽",
    "博览",
    "展覽",
    "展览",
    # 电商出海 / 国际贸易
    "電商",
    "电商",
    "跨境",
    "跨境電商",
    "跨境电商",
    "出海",
    "e-commerce",
    "ecommerce",
    "國際貿易",
    "国际贸易",
    "全球貿易",
    "全球贸易",
    "外貿",
    "外贸",
    "進出口",
    "进出口",
    "商貿",
    "商贸",
    "貿易展",
    "贸易展",
    # 教育 / 人才
    "教育",
    "學術",
    "学术",
    "人才",
    "青年發展",
    "青年发展",
    "大灣區人才",
    "大湾区人才",
    # 惠民 / 大型民生
    "特區政府",
    "特区政府",
    "政府",
    "消費券",
    "消费券",
    "促消費",
    "促消费",
    "社區福利",
    "社区福利",
    "嘉年華",
    "嘉年华",
    "便民",
    "惠民",
    # 香港级 / 国际级大型节日
    "盛事",
    "Mega Events",
    "大型節日",
    "大型节日",
    "傳統節日",
    "传统节日",
    "節日",
    "节日",
    "節慶",
    "节庆",
    "慶典",
    "庆典",
    "盛典",
    "煙花",
    "烟花",
    "燈飾",
    "灯饰",
    "聖誕",
    "圣诞",
    "Christmas",
    "新年",
    "元旦",
    "國慶",
    "国庆",
    "復活節",
    "复活节",
    "端午",
    "龍舟",
    "龙舟",
    "中秋",
    "舞火龍",
    "舞火龙",
    "除夕",
    "倒數",
    "倒数",
    "國際體育",
    "国际体育",
    "國際會議",
    "国际会议",
    "國際展覽",
    "国际展览",
    # 公共假期活动
    "公眾假期",
    "公众假期",
    "公眾假",
    "公众假",
    "法定假期",
    "長假期",
    "长假期",
    "假日",
]
HK_FORCE_EXCLUDE_KEYWORDS = [
    # 美术与艺术展
    "美術",
    "美术",
    "藝術展",
    "艺术展",
    "畫展",
    "画展",
    "當代藝術",
    "当代艺术",
    "私人美術館",
    "私人美术馆",
    "攝影展",
    "摄影展",
    "設計",
    "设计",
    "裝置",
    "装置",
    "Livehouse",
    "livehouse",
    "獨立樂團",
    "独立乐团",
    "音樂",
    "音乐",
    "演唱",
    "World Tour",
    "world tour",
    "舞蹈",
    "舞蹈團",
    "舞蹈团",
    "劇場",
    "剧场",
    "戲劇",
    "戏剧",
    "綜藝",
    "综艺",
    "合家歡",
    "合家欢",
    # 商场 / 购物中心引流
    "商場",
    "商场",
    "購物中心",
    "购物中心",
    "購物節",
    "购物节",
    "促銷",
    "促销",
    "快閃",
    "快闪",
    "Pop-up",
    "pop-up",
    "打卡",
    "公仔",
    "聯名",
    "联名",
    "K11",
    "海港城",
    "時代廣場",
    "时代广场",
    "Fashion Walk",
    "雅蘭中心",
    "荷李活商業中心",
    # 小众 / 休闲娱乐
    "市集",
    "手作",
    "工作坊",
    "烘焙",
    "酒吧",
    "微醺",
    "散步",
    "徒步",
    "導賞",
    "导赏",
    "派對",
    "派对",
    "Bubble",
    "bubble",
    "Planet",
    "planet",
]


def _strip_html(text: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _format_date_range(start: str, end: str) -> str:
    if start and end and start != end:
        return f"{start} - {end}"
    return start or end or ""


def _extract_event_objects(html: str) -> list[dict]:
    """从页面 script/state 中提取含 organizers 字段的活动对象。"""
    # 页面内为转义 JSON，对象以 {"id":"数字" 开头
    pattern = re.compile(
        r'\{"id":"(?P<id>\d+)","title":"(?P<title>(?:\\.|[^"\\])*)","enTitle":(?P<en>.*?),"eventCategories":\[(?P<cats>.*?)\],.*?"organizers":\[(?P<orgs>.*?)\].*?\}',
        re.S,
    )
    results: list[dict] = []
    seen: set[str] = set()

    for m in pattern.finditer(html):
        event_id = m.group("id")
        if event_id in seen:
            continue
        seen.add(event_id)

        chunk = m.group(0)
        # 从 chunk 中继续提取常用字段
        def pick(field: str) -> str:
            fm = re.search(rf'"{field}":"((?:\\.|[^"\\])*)"', chunk)
            return fm.group(1).replace("\\/", "/") if fm else ""

        categories = re.findall(r'"((?:\\.|[^"\\])*)"', m.group("cats"))
        categories = [c.replace('\\"', '"') for c in categories]
        orgs_raw = m.group("orgs")
        organizers = re.findall(r'"((?:\\.|[^"\\])*)"', orgs_raw)
        organizers = [o.replace('\\"', '"') for o in organizers]

        results.append(
            {
                "id": event_id,
                "title": m.group("title").replace('\\"', '"'),
                "startDate": pick("startDate"),
                "endDate": pick("endDate"),
                "shortDescription": pick("shortDescription"),
                "description": pick("description"),
                "pageUrl": pick("pageUrl"),
                "categories": categories,
                "organizers": organizers,
            }
        )

    return results


def _matches_hk_event_policy(
    row: dict,
    *,
    exclude_keywords: list[str],
    require_include_keywords: bool = True,
) -> bool:
    name = _strip_html(row.get("title", ""))
    desc = _strip_html(row.get("shortDescription") or row.get("description") or "")
    org_text = " ".join(row.get("organizers") or [])
    cat_text = " ".join(row.get("categories") or [])
    text = f"{name} {desc} {org_text} {cat_text}"
    text_lower = text.lower()

    force_exclude = [*exclude_keywords, *HK_FORCE_EXCLUDE_KEYWORDS]
    if any(keyword and keyword.lower() in text_lower for keyword in force_exclude):
        return False
    if not require_include_keywords:
        return True
    return any(keyword and keyword.lower() in text_lower for keyword in HK_INCLUDE_KEYWORDS)


def fetch_events(
    *,
    days_ahead: int = 90,
    start_after_days: int = 7,
    exclude_keywords: list[str] | None = None,
    require_include_keywords: bool = True,
) -> list[EventItem]:
    scraper = cloudscraper.create_scraper()
    response = scraper.get(EVENTS_URL, timeout=45)
    response.raise_for_status()
    response.encoding = "utf-8"
    html = response.text

    if "Just a moment" in html:
        raise RuntimeError("Discover Hong Kong 页面被 Cloudflare 拦截，请稍后重试")

    raw_events = _extract_event_objects(html)
    logger.info("Parsed %d events from Discover Hong Kong HTML", len(raw_events))

    today = date.today()
    exclude = exclude_keywords if exclude_keywords is not None else DEFAULT_EXCLUDE

    items: list[EventItem] = []
    for row in raw_events:
        name = _strip_html(row.get("title", ""))
        if not name:
            continue
        org_text = "、".join(row.get("organizers") or [])
        if not _matches_hk_event_policy(
            row,
            exclude_keywords=exclude,
            require_include_keywords=require_include_keywords,
        ):
            continue

        start_s = row.get("startDate", "")
        end_s = row.get("endDate", "")
        start_d = parse_start_date(start_s)
        if not start_date_in_window(
            start_d,
            today=today,
            start_after_days=start_after_days,
            days_ahead=days_ahead,
        ):
            continue

        desc = _strip_html(row.get("shortDescription") or row.get("description") or "")
        desc = re.sub(r"\\r\\n|\\n", " ", desc)
        if not desc:
            desc = "（详见活动页面）"

        url = row.get("pageUrl", "")
        if url and not url.startswith("http"):
            url = "https://www.discoverhongkong.com" + url

        items.append(
            EventItem(
                event_id=f"dhk-{row['id']}",
                name=name,
                date_text=_format_date_range(start_s[:10], end_s[:10]),
                start_date=start_s[:10] if start_s else "",
                end_date=end_s[:10] if end_s else "",
                organizer=org_text or "未知主办方",
                description=desc,
                location="",
                url=url,
                source="discoverhongkong",
            )
        )

    items.sort(key=lambda e: (e.start_date or "9999", e.name))
    return items
