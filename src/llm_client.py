"""内网 Workflow API 客户端（Dify Workflow：POST /v1/workflows/run）。"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

from .scraper.models import EventItem
from .theme_tags import get_event_themes, theme_label

logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW_URL = "http://10.0.62.178:3100/v1/workflows/run"


@dataclass
class WorkflowConfig:
    api_url: str
    api_key: str
    user: str = "feishu-bot"
    timeout: int = 60
    query_input_key: str = "query"
    events_input_key: str = "events_json"
    meta_input_key: str = "search_meta_json"
    user_context_input_key: str = "user_context"
    mode_input_key: str = "conversation_mode"
    combined_input_key: str = ""
    response_answer_key: str = "ai_output"


def load_workflow_config() -> WorkflowConfig | None:
    api_url = os.getenv("WORKFLOW_API_URL", DEFAULT_WORKFLOW_URL).strip()
    api_key = os.getenv("WORKFLOW_API_KEY", "").strip()
    if not api_key:
        return None

    return WorkflowConfig(
        api_url=api_url or DEFAULT_WORKFLOW_URL,
        api_key=api_key,
        user=os.getenv("WORKFLOW_USER", "feishu-bot").strip() or "feishu-bot",
        timeout=int(os.getenv("WORKFLOW_TIMEOUT", "180")),
        query_input_key=os.getenv("WORKFLOW_INPUT_QUERY", "query").strip() or "query",
        events_input_key=os.getenv("WORKFLOW_INPUT_EVENTS", "events_json").strip() or "events_json",
        meta_input_key=os.getenv("WORKFLOW_INPUT_META", "search_meta_json").strip() or "search_meta_json",
        user_context_input_key=os.getenv("WORKFLOW_INPUT_USER_CONTEXT", "user_context").strip() or "user_context",
        mode_input_key=os.getenv("WORKFLOW_INPUT_MODE", "conversation_mode").strip() or "conversation_mode",
        combined_input_key=os.getenv("WORKFLOW_COMBINED_INPUT", "").strip(),
        response_answer_key=os.getenv("WORKFLOW_RESPONSE_ANSWER", "ai_output").strip() or "ai_output",
    )


def events_to_json(events: list[EventItem]) -> str:
    payload = []
    for event in _events_for_workflow(events):
        themes = sorted(get_event_themes(event))
        payload.append(
            {
                "event_id": event.event_id,
                "name": event.name,
                "start_date": event.start_date,
                "end_date": event.end_date,
                "date_text": event.date_text,
                "location": event.location,
                "organizer": event.organizer,
                "description": event.description,
                "url": event.url,
                "source": event.source,
                "themes": themes,
                "theme_labels": [theme_label(t) for t in themes],
                "topic": event.topic,
            }
        )
    return json.dumps(payload, ensure_ascii=False)


def _workflow_max_events() -> int:
    return max(1, int(os.getenv("WORKFLOW_MAX_EVENTS", "6")))


def _workflow_desc_limit() -> int:
    return max(80, int(os.getenv("WORKFLOW_DESC_MAX_CHARS", "200")))


def _workflow_query_max_chars() -> int:
    return max(1, int(os.getenv("WORKFLOW_QUERY_MAX_CHARS", "48")))


def _truncate_workflow_query(query: str) -> str:
    """Dify Workflow 的 query 输入有长度上限；完整问句保留在 search_meta_json。"""
    limit = _workflow_query_max_chars()
    text = query.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _events_for_workflow(events: list[EventItem]) -> list[EventItem]:
    """发给 Dify 的活动列表：条数更少、摘要更短，降低超时概率。"""
    limit = _workflow_max_events()
    desc_limit = _workflow_desc_limit()
    trimmed: list[EventItem] = []
    for event in events[:limit]:
        description = (event.description or "").strip()
        if len(description) > desc_limit:
            description = description[: desc_limit - 3].rstrip() + "..."
        name = event.name
        if len(name) > 120:
            name = name[:117].rstrip() + "..."
        trimmed.append(
            EventItem(
                event_id=event.event_id,
                name=name,
                date_text=event.date_text,
                start_date=event.start_date,
                end_date=event.end_date,
                organizer=event.organizer,
                description=description,
                location=event.location,
                url=event.url,
                source=event.source,
                topic=event.topic,
            )
        )
    return trimmed


class WorkflowClient:
    """调用 Dify Workflow API，默认 blocking 模式。"""

    def __init__(self, config: WorkflowConfig):
        self.config = config

    def generate_reply(
        self,
        *,
        query: str,
        events: list[EventItem],
        search_meta: dict[str, Any] | None = None,
        user_context: str = "",
        conversation_mode: str = "search",
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        inputs = _build_inputs(
            self.config,
            query=query,
            events=events,
            search_meta=search_meta,
            user_context=user_context,
            conversation_mode=conversation_mode,
        )
        body = {
            "inputs": inputs,
            "response_mode": "blocking",
            "user": self.config.user,
        }

        logger.info("Calling workflow API: %s inputs=%s", self.config.api_url, list(inputs))
        started = time.monotonic()
        response = _post_with_timeout_retry(
            self.config.api_url,
            headers=headers,
            json=body,
            timeout=self.config.timeout,
        )
        elapsed = time.monotonic() - started
        logger.info("Workflow API responded in %.1fs (timeout=%ss)", elapsed, self.config.timeout)

        if not response.ok:
            _raise_api_error(response)

        data = response.json()
        _ensure_workflow_succeeded(data)

        answer = _extract_answer(data, self.config.response_answer_key)
        if not answer:
            raise ValueError(f"Workflow response missing output text: {data}")
        return _sanitize_model_output(answer.strip())


def _post_with_timeout_retry(
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any],
    timeout: int,
) -> requests.Response:
    """POST once; optional single retry when WORKFLOW_TIMEOUT_RETRY=1."""
    try:
        return requests.post(url, headers=headers, json=json, timeout=timeout)
    except requests.exceptions.Timeout as first_timeout:
        retry = os.getenv("WORKFLOW_TIMEOUT_RETRY", "0").strip().lower() in {"1", "true", "yes"}
        if not retry:
            raise
        logger.warning(
            "Workflow read timeout after %ss, retrying once: %s",
            timeout,
            first_timeout,
        )
        return requests.post(url, headers=headers, json=json, timeout=timeout)


def _sanitize_model_output(text: str) -> str:
    """去掉部分模型返回的思考过程，只保留给用户看的正文。"""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _build_inputs(
    config: WorkflowConfig,
    *,
    query: str,
    events: list[EventItem],
    search_meta: dict[str, Any] | None = None,
    user_context: str = "",
    conversation_mode: str = "search",
) -> dict[str, str]:
    events_json = events_to_json(events)
    analysis_instructions = ""
    if search_meta and isinstance(search_meta.get("analysis_instructions"), str):
        analysis_instructions = search_meta["analysis_instructions"]

    if config.combined_input_key:
        payload = json.dumps(
            {
                "query": query,
                "events": json.loads(events_json),
                "search_meta": search_meta or {},
                "user_context": user_context,
                "conversation_mode": conversation_mode,
                "analysis_instructions": analysis_instructions,
            },
            ensure_ascii=False,
        )
        return {config.combined_input_key: payload}

    inputs = {
        config.query_input_key: _truncate_workflow_query(query),
        config.events_input_key: events_json,
        config.mode_input_key: conversation_mode,
    }
    if search_meta is not None:
        inputs[config.meta_input_key] = json.dumps(search_meta, ensure_ascii=False)
    inputs[config.user_context_input_key] = user_context.strip()
    return inputs


def _raise_api_error(response: requests.Response) -> None:
    try:
        payload = response.json()
        message = payload.get("message") or payload.get("code") or response.text
    except ValueError:
        message = response.text
    raise RuntimeError(f"Workflow API HTTP {response.status_code}: {message}")


def _ensure_workflow_succeeded(data: dict[str, Any]) -> None:
    detail = data.get("data")
    if not isinstance(detail, dict):
        return

    status = detail.get("status")
    if status == "failed":
        error = detail.get("error") or "unknown workflow error"
        raise RuntimeError(f"Workflow execution failed: {error}")

    if status and status not in {"succeeded", "running"}:
        raise RuntimeError(f"Workflow ended with status={status}")


def _extract_answer(data: dict[str, Any], answer_key: str) -> str:
    outputs = data.get("data", {}).get("outputs") if isinstance(data.get("data"), dict) else None
    if isinstance(outputs, dict):
        for key in (answer_key, "ai_output", "text", "answer", "result", "output"):
            value = outputs.get(key)
            if isinstance(value, str) and value.strip():
                return value

    if isinstance(data.get("answer"), str):
        return data["answer"]

    if answer_key in data and isinstance(data[answer_key], str):
        return data[answer_key]

    return ""
