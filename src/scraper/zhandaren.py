"""Zhandaren (zhandaren.com) Greater Bay Area exhibition scraper."""







from __future__ import annotations







import json



import logging



import re
import time

from datetime import date



from html import unescape



from typing import Any







import cloudscraper







from .filters import parse_start_date, start_date_in_window



from .models import EventItem







logger = logging.getLogger(__name__)







BASE_URL = "https://new.zhandaren.com"
DETAIL_BASE_URL = "https://www.zhandaren.com"
DETAIL_REQUEST_DELAY_SEC = 0.4
DETAIL_MAX_RETRIES = 3

USER_AGENT = (



    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "



    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"



)










INDUSTRY_FILTERS = {
    "eldercare": {"id": "I01HR6T3XPTEQ8AVS7AA10W2M9A", "keyword": "0", "label": "\u517b\u8001"},
    "education": {"id": "I01HQ9SSWY8SG9T0ZCPW8S7QQWV", "keyword": "%E6%95%99%E8%82%B2", "label": "\u6559\u80b2"},
    "communication": {"id": "I01K2K3DY25889TWT7K4VQXPXEK", "keyword": "0", "label": "\u901a\u4fe1"},
    "electronics": {"id": "I01HKP50V600VYJ0PKYDTREGXSY", "keyword": "0", "label": "\u7535\u5b50"},
}

ALLOWED_LOCATION_CODES = {"232", "234", "235", "236", "233", "237", "3535"}









KNOWN_CITY_NAMES = [



    "\u5e7f\u5dde\u5e02",



    "\u6df1\u5733\u5e02",



    "\u9999\u6e2f\u7279\u522b\u884c\u653f\u533a",



    "\u73e0\u6d77\u5e02",



    "\u4e1c\u839e\u5e02",



    "\u4e2d\u5c71\u5e02",



    "\u4f5b\u5c71\u5e02",



    "\u60e0\u5dde\u5e02",



    "\u6c5f\u95e8\u5e02",



    "\u6fb3\u95e8",



]







S01_ID = re.compile(r'"(S01[A-Z0-9]+)"')



DATE_RANGE = re.compile(r'"(\d{4}-\d{2}-\d{2})","(\d{4}-\d{2}-\d{2})"')



SHOW_DATE = re.compile(r'"(\d{4}/\d{2}/\d{2}\s*~\s*\d{2}/\d{2})"')



NAME_AFTER_PROJECT = re.compile(r',"P01[A-Z0-9]+","([^"]+)"')



ALIAS_AFTER_PROJECT = re.compile(r',"P01[A-Z0-9]+","[^"]+","([^"]*)"')



GUANGDONG_CITY = re.compile(r"\u5e7f\u4e1c\u7701([^\s,\"]{2,8}?\u5e02)")

GBA_LOCATION_KEYWORDS = [

    "\u5e7f\u5dde",

    "\u6df1\u5733",

    "\u9999\u6e2f",

    "\u73e0\u6d77",

    "\u4e1c\u839e",

    "\u4f5b\u5c71",

    "\u60e0\u5dde",

    "\u4e2d\u5c71",

    "\u6c5f\u95e8",

    "\u6fb3\u95e8",

]

DETAIL_VENUE = re.compile(r"\u4e3e\u529e\u573a\u9986.*?prop-value--text[^>]*>(?:<a[^>]*>)?([^<]+)", re.S)

DETAIL_ADDRESS = re.compile(r"\u4e3e\u529e\u5730\u5740.*?prop-value--text[^>]*>([^<]+)", re.S)














def _build_industry_urls(city_codes: set[str]) -> list[str]:
    urls: list[str] = []
    for item in INDUSTRY_FILTERS.values():
        industry_id = item["id"]
        keyword = item["keyword"]
        for city_code in sorted(city_codes):
            urls.append(f"{BASE_URL}/exhibition/{industry_id}-{city_code}-0-{keyword}-1-1")
    return urls


def _parse_exhibition_url_parts(url: str) -> tuple[str, str] | None:
    tail = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    parts = tail.split("-")
    if len(parts) < 6:
        return None
    industry_id = parts[0]
    location_code = parts[1]
    return industry_id, location_code


def _matches_industry_location_url(url: str) -> bool:
    parsed = _parse_exhibition_url_parts(url)
    if parsed is None:
        return False
    industry_id, location_code = parsed
    allowed_industry_ids = {item["id"] for item in INDUSTRY_FILTERS.values()}
    return industry_id in allowed_industry_ids and location_code in ALLOWED_LOCATION_CODES


def _format_date_range(start: str, end: str) -> str:



    if start and end and start != end:



        start_d = parse_start_date(start)



        end_d = parse_start_date(end)



        if start_d and end_d and start_d.year == end_d.year and start_d.month == end_d.month:



            return f"{start} ~ {end_d.strftime('%m/%d')}"



        return f"{start} ~ {end}"



    return start or end or ""











def _decode_json_string(value: str) -> str:



    try:



        return json.loads(f'"{value}"')



    except json.JSONDecodeError:



        return unescape(value)











def _extract_city(text: str) -> str:



    for city in KNOWN_CITY_NAMES:



        if city in text:



            return city







    match = GUANGDONG_CITY.search(text)



    if match:



        return match.group(1)



    return ""





def _strip_html(text: str) -> str:

    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))

    return re.sub(r"\s+", " ", text).strip()





def _extract_detail_location(html: str) -> tuple[str, str, str]:

    venue_match = DETAIL_VENUE.search(html)

    address_match = DETAIL_ADDRESS.search(html)

    venue = _strip_html(venue_match.group(1)) if venue_match else ""

    address = _strip_html(address_match.group(1)) if address_match else ""

    city = _extract_city(f"{venue} {address}")

    return venue, address, city








def _short_summary(text: str) -> str:
    text = _strip_html(text)
    text = re.sub(r"\\r\\n|\\n|\s+", " ", text).strip()
    if not text:
        return ""

    sentence_marks = {"?", "?", "?", "!", "?", "?", ";"}
    sentences: list[str] = []
    current: list[str] = []
    for char in text:
        current.append(char)
        if char in sentence_marks:
            sentences.append("".join(current).strip())
            current = []
            if len(sentences) >= 2:
                break
    if current and len(sentences) < 2:
        sentences.append("".join(current).strip())

    summary = "".join(sentences).strip() if sentences else text
    if len(summary) > 160:
        summary = summary[:157].rstrip() + "..."
    return summary


def _extract_detail_intro(html: str) -> str:
    # Prefer the visible rich-text body under the exhibition detail module.
    match = re.search(
        r'<div class="venue-intro"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        html,
        re.S,
    )
    if match:
        intro = _short_summary(match.group(1))
        if intro:
            return intro

    meta_match = re.search(r'<meta name="description" content="([^"]+)"', html, re.S)
    if meta_match:
        meta = _short_summary(meta_match.group(1))
        if meta and "\u5c55\u5927\u4eba\u4f1a\u5c55\u5e73\u53f0" not in meta:
            return meta
    return ""


def _is_gba_location(text: str) -> bool:

    return any(keyword in text for keyword in GBA_LOCATION_KEYWORDS)


NON_GBA_CITY_KEYWORDS = [
    "成都",
    "北京",
    "重庆",
    "武汉",
    "西安",
    "杭州",
    "南京",
    "苏州",
    "天津",
    "青岛",
    "大连",
    "郑州",
    "长沙",
    "沈阳",
    "哈尔滨",
    "昆明",
    "贵阳",
    "南宁",
    "太原",
    "济南",
    "合肥",
    "南昌",
    "福州",
    "石家庄",
    "长春",
    "兰州",
    "乌鲁木齐",
    "呼和浩特",
    "宁波",
    "无锡",
    "温州",
    "义乌",
    "金华",
]


def _has_non_gba_city(text: str) -> bool:
    if "成都" in text:
        return True
    if "上海市" in text:
        return True
    # 「上海」需排除香港「上海街」等误报：仅当无大湾区锚点时才视为站外城市
    if "上海" in text and "上海街" not in text and not _is_gba_location(text):
        return True
    return any(keyword in text for keyword in NON_GBA_CITY_KEYWORDS)


def _passes_gba_location_filter(
    city_name: str,
    detail_city: str,
    detail_venue: str,
    detail_address: str,
) -> bool:
    location_text = " ".join(
        part.strip()
        for part in (city_name, detail_city, detail_venue, detail_address)
        if part and part.strip()
    )
    if not location_text:
        return False
    if _has_non_gba_city(location_text):
        return False
    return _is_gba_location(location_text)













def _parse_page_items(html: str, *, source_url: str = "") -> list[dict[str, str]]:



    items: list[dict[str, str]] = []



    seen: set[str] = set()







    for id_match in S01_ID.finditer(html):



        exhibition_id = id_match.group(1)



        if exhibition_id in seen:



            continue







        chunk = html[id_match.start() : id_match.start() + 1800]



        name_match = NAME_AFTER_PROJECT.search(chunk)



        date_match = DATE_RANGE.search(chunk)



        if not name_match or not date_match:



            continue







        seen.add(exhibition_id)



        alias_match = ALIAS_AFTER_PROJECT.search(chunk)



        show_date_match = SHOW_DATE.search(chunk)



        search_tail = chunk[date_match.end() :]







        items.append(



            {



                "exhibition_id": exhibition_id,



                "name": _decode_json_string(name_match.group(1)),



                "alias": _decode_json_string(alias_match.group(1)) if alias_match else "",



                "start_date": date_match.group(1),



                "end_date": date_match.group(2),



                "show_date": show_date_match.group(1) if show_date_match else "",



                "city_name": _extract_city(search_tail),



                "source_url": source_url,



            }



        )







    return items











def _make_scraper(*, referer: str | None = None) -> cloudscraper.CloudScraper:
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": referer or f"{BASE_URL}/",
        }
    )
    return scraper


def _fetch_html(scraper: cloudscraper.CloudScraper, url: str) -> str:
    response = scraper.get(url, timeout=45)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def _is_error_page(response: Any) -> bool:
    return response.status_code == 404 or "/error" in str(response.url)


def _fetch_detail_html(exhibition_id: str) -> str | None:
    """Fetch exhibition detail; retries with fresh session when rate-limited."""
    url = f"{DETAIL_BASE_URL}/exhibition/info?id={exhibition_id}"
    last_error: Exception | None = None
    for attempt in range(DETAIL_MAX_RETRIES):
        if attempt:
            time.sleep(DETAIL_REQUEST_DELAY_SEC * (attempt + 1))
        scraper = _make_scraper(referer=f"{BASE_URL}/")
        try:
            response = scraper.get(url, timeout=45, allow_redirects=True)
            if _is_error_page(response):
                last_error = RuntimeError(f"error page for {exhibition_id}")
                continue
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except Exception as exc:
            last_error = exc
    logger.warning(
        "Zhandaren detail unavailable for %s after %s tries: %s",
        exhibition_id,
        DETAIL_MAX_RETRIES,
        last_error,
    )
    return None











def _dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:



    by_id: dict[str, dict[str, str]] = {}



    for row in rows:



        existing = by_id.get(row["exhibition_id"])



        if existing is None:



            by_id[row["exhibition_id"]] = row



            continue







        if not existing.get("city_name") and row.get("city_name"):



            existing["city_name"] = row["city_name"]



        if not existing.get("show_date") and row.get("show_date"):



            existing["show_date"] = row["show_date"]







    return list(by_id.values())














CITY_CODE_KEYWORDS = {
    "232": ["广州", "广州市"],
    "233": ["佛山", "佛山市"],
    "234": ["深圳", "深圳市"],
    "235": ["珠海", "珠海市"],
    "236": ["东莞", "东莞市"],
    "237": ["惠州", "惠州市"],
    "3535": ["香港", "香港特别行政区"],
}



def fetch_events(



    *,



    days_ahead: int = 90,



    start_after_days: int = 7,




    include_hong_kong_page: bool = True,



) -> list[EventItem]:



    """Fetch GBA-related exhibitions and filter by start_date only."""


    today = date.today()







    scraper = _make_scraper()

    city_codes = set(ALLOWED_LOCATION_CODES)



    if not include_hong_kong_page:



        city_codes.discard("3535")



    urls = _build_industry_urls(city_codes)







    rows: list[dict[str, str]] = []



    for url in urls:



        try:



            html = _fetch_html(scraper, url)



            parsed_rows = _parse_page_items(html, source_url=url)



            # When a filter URL has no exact results, Zhandaren falls back to the default list.

            if len(parsed_rows) > 3:



                continue



            rows.extend(parsed_rows)



        except Exception:



            logger.exception("Failed to fetch Zhandaren page: %s", url)







    events: list[EventItem] = []



    seen_event_ids: set[str] = set()



    for row in rows:



        if not _matches_industry_location_url(row.get("source_url", "")):



            continue



        name = row["name"]



        alias = row.get("alias", "")



        city_name = row.get("city_name", "")



        exhibition_id = row["exhibition_id"]



        if exhibition_id in seen_event_ids:



            continue

        detail_venue = ""
        detail_address = ""
        detail_city = ""
        detail_intro = ""

        detail_html = _fetch_detail_html(exhibition_id)
        if detail_html:
            detail_venue, detail_address, detail_city = _extract_detail_location(detail_html)
            detail_intro = _extract_detail_intro(detail_html)
        time.sleep(DETAIL_REQUEST_DELAY_SEC)

        if not _passes_gba_location_filter(
            city_name,
            detail_city,
            detail_venue,
            detail_address,
        ):
            continue

        city_name = detail_city or city_name







        start = parse_start_date(row["start_date"])



        if not start_date_in_window(



            start,



            today=today,



            start_after_days=start_after_days,



            days_ahead=days_ahead,



        ):



            continue







        seen_event_ids.add(exhibition_id)



        events.append(



            EventItem(



                event_id=f"zdr-{exhibition_id}",



                name=name,



                date_text=row.get("show_date") or _format_date_range(row["start_date"], row["end_date"]),



                start_date=row["start_date"],



                end_date=row["end_date"],



                organizer="\u5c55\u5927\u4eba",



                description=detail_intro or alias or detail_venue or city_name or "\uff08\u8be6\u89c1\u5c55\u4f1a\u9875\u9762\uff09",



                location=detail_address or detail_venue or city_name,



                url=f"{DETAIL_BASE_URL}/exhibition/info?id={exhibition_id}",



                source="zhandaren",



            )



        )







    events.sort(key=lambda event: (event.start_date or "9999", event.name))



    logger.info("Zhandaren matched %d exhibitions after filters", len(events))



    return events



