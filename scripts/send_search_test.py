"""Send hybrid search test replies to Feishu group."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from main import create_client
from src.lark_ws_service import load_schedule_target
from src.message_builder import build_text_content
from src.search_service import format_local_reply, search_events

QUERIES = [
    "请推荐大湾区科技展会",
    "数据中心 算力",
    "养老 健康",
]

CONFIG = ROOT / "config" / "schedules.yaml"
SCHEDULE_NAME = "weekly-hk-events"


def main() -> None:
    target = load_schedule_target(CONFIG, SCHEDULE_NAME)
    chat_id = target["chat_ids"][0]
    search_config = dict(target.get("message") or {})

    client = create_client()
    intro = (
        "【Hybrid 检索测试】\n"
        "以下为 @机器人 检索模拟结果（BM25 硬过滤 + 向量 rerank/fallback）。"
    )
    client.send_message_to_chat(chat_id, "text", build_text_content(intro))
    print("sent intro")

    for query in QUERIES:
        result = search_events(
            query,
            limit=int(search_config.get("max_items", 15)),
            start_after_days=int(search_config.get("start_after_days", 0)),
            days_ahead=int(search_config.get("days_ahead", 120)),
            sources=search_config.get("sources"),
        )
        reply = format_local_reply(
            result.events,
            query=query,
            match_mode=result.match_mode,
        )
        header = f"\n\n---\n🔍 测试问句：{query}\n模式：{result.match_mode}\n命中：{len(result.events)} 条"
        text = reply + header
        if len(text) > 3500:
            text = text[:3500] + "\n...(内容过长已截断)"
        client.send_message_to_chat(chat_id, "text", build_text_content(text))
        print(f"sent query: {query} ({result.match_mode}, {len(result.events)} hits)")

    print(f"done, chat_id={chat_id}")


if __name__ == "__main__":
    main()
