"""HKTDC Events scraper (home.hktdc.com / event.hktdc.com)."""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from .filters import parse_start_date, start_date_in_window
from .models import EventItem

logger = logging.getLogger(__name__)

EVENTS_PAGE = "https://home.hktdc.com/en/join-fairs-conferences-events"
CALENDAR_BASE = "https://home.hktdc.com/resources/calendar"
CMS_API = "https://api-cms.hktdc.com"
EMS_EVENT_URL = f"{CMS_API}/ems/v1/event"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HK_TZ = timezone(timedelta(hours=8))
LOCALE_PRIORITY = ("zh-hant", "zh-hans", "en")
_DATE_FMT = "%d %b %Y %H:%M"
_HTML_TAG = re.compile(r"<[^>]+>")
_META_DESC_RE = re.compile(
    r'<meta[^>]+(?:name=["\']description["\'][^>]+content=["\']([^"\']+)["\']'
    r'|content=["\']([^"\']+)["\'][^>]+name=["\']description["\'])',
    re.I,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)


def _format_date_range(start: str, end: str) -> str:
    if start and end and start != end:
        start_d = parse_start_date(start)
        end_d = parse_start_date(end)
        if start_d and end_d and start_d.year == end_d.year and start_d.month == end_d.month:
            return f"{start_d.month}月{start_d.day}-{end_d.day}日"
        if start_d and end_d:
            return f"{start_d.month}月{start_d.day}日-{end_d.month}月{end_d.day}日"
    if start:
        start_d = parse_start_date(start)
        if start_d:
            return f"{start_d.month}月{start_d.day}日"
    return start or end or "日期待定"


def _parse_event_datetime(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, _DATE_FMT).replace(tzinfo=HK_TZ).date()
    except ValueError:
        return parse_start_date(value)


def _months_covering_window(*, today: date, days_ahead: int) -> list[tuple[int, int]]:
    end = today + timedelta(days=days_ahead)
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
            "Referer": EVENTS_PAGE,
        }
    )
    return session


def _fetch_calendar_hits(session: requests.Session, *, today: date, days_ahead: int) -> list[dict[str, Any]]:
    hits_by_id: dict[str, dict[str, Any]] = {}
    for year, month in _months_covering_window(today=today, days_ahead=days_ahead):
        url = f"{CALENDAR_BASE}/{year}/{year}-{month:02d}-calendar_en.json"
        try:
            response = session.get(url, timeout=45)
        except requests.RequestException as exc:
            logger.warning("HKTDC calendar fetch failed %s: %s", url, exc)
            continue
        if response.status_code != 200:
            continue
        payload = response.json()
        for hit in payload.get("hits") or []:
            doc_id = str(hit.get("docRefId") or "").strip()
            key = doc_id or str(hit.get("title") or "").strip()
            if key:
                hits_by_id[key] = hit
    logger.info("HKTDC calendar loaded %d unique events", len(hits_by_id))
    return list(hits_by_id.values())


def _fetch_ems_content(
    session: requests.Session,
    doc_ref_id: str,
    *,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if doc_ref_id in cache:
        return cache[doc_ref_id]
    content: dict[str, Any] = {}
    try:
        response = session.get(EMS_EVENT_URL, params={"eventId": doc_ref_id}, timeout=30)
        response.raise_for_status()
        by_locale: dict[str, dict[str, Any]] = {}
        for row in response.json().get("results") or []:
            row_content = row.get("content") or {}
            locale = str(row_content.get("locale") or "").lower()
            if locale:
                by_locale[locale] = row_content
        content = {}
        for locale in LOCALE_PRIORITY:
            if locale in by_locale:
                content = by_locale[locale]
                break
        else:
            if by_locale:
                content = next(iter(by_locale.values()))
    except requests.RequestException as exc:
        logger.debug("HKTDC EMS lookup failed for %s: %s", doc_ref_id, exc)
    cache[doc_ref_id] = content
    return content


def _strip_html(text: str) -> str:
    cleaned = _HTML_TAG.sub(" ", text or "")
    return html.unescape(re.sub(r"\s+", " ", cleaned)).strip()


def _fetch_page_blurb(session: requests.Session, url: str) -> str:
    if not url.startswith("http"):
        return ""
    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("HKTDC page blurb fetch failed %s: %s", url, exc)
        return ""

    page = response.text
    for pattern in (_OG_DESC_RE, _META_DESC_RE):
        match = pattern.search(page)
        if not match:
            continue
        blurb = _strip_html(match.group(1) or match.group(2) or "")
        if len(blurb) >= 20:
            return blurb
    return ""


def _pick_name(hit: dict[str, Any], ems: dict[str, Any]) -> str:
    for key in ("event_name", "title"):
        value = str(ems.get(key) or hit.get(key) or "").strip()
        if value:
            return value
    return str(hit.get("bodyShortForm") or hit.get("title") or "HKTDC 活动").strip()


def _pick_blurb(
    hit: dict[str, Any],
    ems: dict[str, Any],
    *,
    event_name: str,
    session: requests.Session | None = None,
    url: str = "",
) -> str:
    candidates: list[str] = []
    for source in (hit, ems):
        for key in ("bodyShortForm", "short_description", "description", "event_description"):
            value = _strip_html(str(source.get(key) or ""))
            if value and value not in candidates:
                candidates.append(value)

    name_norm = event_name.strip().lower()
    blurb = ""
    for candidate in candidates:
        if len(candidate) >= 30 and candidate.lower() != name_norm:
            blurb = candidate
            break
    if not blurb:
        for candidate in candidates:
            if candidate and candidate.lower() != name_norm:
                blurb = candidate
                break

    if (not blurb or len(blurb) < 40) and session and url:
        page_blurb = _fetch_page_blurb(session, url)
        if page_blurb and page_blurb.lower() != name_norm:
            blurb = page_blurb
    return blurb


def _build_description(
    hit: dict[str, Any],
    ems: dict[str, Any],
    *,
    event_name: str = "",
    session: requests.Session | None = None,
    url: str = "",
) -> str:
    parts: list[str] = []
    blurb = _pick_blurb(hit, ems, event_name=event_name, session=session, url=url)
    if blurb:
        parts.append(blurb)

    meta: list[str] = []
    industries = hit.get("industries") or []
    if industries:
        meta.append("行业：" + "、".join(str(x) for x in industries if x))
    formats = hit.get("eventFormats") or []
    if formats:
        meta.append("形式：" + "、".join(str(x) for x in formats if x))
    if hit.get("eventOnlineInd"):
        meta.append("含线上环节")
    if meta:
        parts.append(" ".join(meta))
    return " ".join(parts) or "（详见 HKTDC 活动页面）"


def _build_location(hit: dict[str, Any], ems: dict[str, Any]) -> str:
    for source in (ems, hit):
        for key in ("event_location", "location", "regionsForDisplay", "regions"):
            value = source.get(key)
            if isinstance(value, dict):
                from .location_format import _names_from_mapping

                names = _names_from_mapping(value)
                if names:
                    return "、".join(dict.fromkeys(names))
            if isinstance(value, list):
                from .location_format import _names_from_region_list

                names = _names_from_region_list(value)
                if names:
                    return "、".join(dict.fromkeys(names))
            text = str(value or "").strip()
            if text and not text.startswith("{"):
                return text
    if hit.get("eventIsOutsideHK"):
        return "香港以外"
    return "香港"


def _build_url(hit: dict[str, Any], ems: dict[str, Any]) -> str:
    for source in (hit, ems):
        url = str(source.get("landingUrl") or source.get("event_url") or source.get("url") or "").strip()
        if url.startswith("http"):
            return url
    fair_code = str(hit.get("fairCode") or hit.get("fair_code") or "").strip()
    if fair_code:
        return f"https://www.hktdc.com/event/{fair_code}/tc"
    return EVENTS_PAGE


def _hit_to_event(
    hit: dict[str, Any],
    *,
    session: requests.Session,
    ems_cache: dict[str, dict[str, Any]],
    today: date,
    start_after_days: int,
    days_ahead: int,
) -> EventItem | None:
    doc_ref_id = str(hit.get("docRefId") or "").strip()
    if not doc_ref_id:
        return None

    start = _parse_event_datetime(str(hit.get("eventStartDate") or ""))
    end = _parse_event_datetime(str(hit.get("eventEndDate") or ""))
    if not start_date_in_window(
        start,
        today=today,
        start_after_days=start_after_days,
        days_ahead=days_ahead,
    ):
        return None

    ems = _fetch_ems_content(session, doc_ref_id, cache=ems_cache)
    name = _pick_name(hit, ems)
    url = _build_url(hit, ems)
    start_s = start.isoformat() if start else ""
    end_s = end.isoformat() if end else ""
    organizers = hit.get("eventOrganizer") or ems.get("event_organizer") or ["香港贸易发展局"]
    if isinstance(organizers, list):
        organizer = "、".join(str(x) for x in organizers if x)
    else:
        organizer = str(organizers or "香港贸易发展局")

    return EventItem(
        event_id=f"hktdc-{doc_ref_id}",
        name=name,
        date_text=_format_date_range(start_s, end_s),
        start_date=start_s,
        end_date=end_s,
        organizer=organizer or "香港贸易发展局",
        description=_build_description(hit, ems, event_name=name, session=session, url=url),
        location=_build_location(hit, ems),
        url=url,
        source="hktdc",
    )


def fetch_events(
    *,
    days_ahead: int = 90,
    start_after_days: int = 7,
    languages: list[str] | None = None,
) -> list[EventItem]:
    """Fetch HKTDC trade events from the official calendar + EMS metadata."""
    _ = languages  # locale handled via EMS zh-hant preference
    today = date.today()
    session = _session()
    hits = _fetch_calendar_hits(session, today=today, days_ahead=days_ahead)
    ems_cache: dict[str, dict[str, Any]] = {}

    items: list[EventItem] = []
    for hit in hits:
        event = _hit_to_event(
            hit,
            session=session,
            ems_cache=ems_cache,
            today=today,
            start_after_days=start_after_days,
            days_ahead=days_ahead,
        )
        if event:
            items.append(event)

    items.sort(key=lambda e: (e.start_date or "9999", e.name))
    logger.info("HKTDC matched %d events after date window filter", len(items))
    return items
