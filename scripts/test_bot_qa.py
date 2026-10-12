"""Local @bot Q&A test (no Feishu send)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.lark_ws_service import load_search_config_from_schedule
from src.llm_client import load_workflow_config
from src.search_service import answer_query

OUT = ROOT / "logs" / "bot_qa_test.txt"
CONFIG = ROOT / "config" / "schedules.yaml"
SCHEDULE = "weekly-hk-events"

QUERIES = [
    "",
    "请推荐大湾区科技展会",
    "数据中心 算力",
    "养老 健康",
    "香港书展",
    "本周有什么活动",
]


def main() -> None:
    if not (ROOT / "data" / "events.db").exists():
        raise SystemExit("events.db missing; run: .venv\\Scripts\\python.exe main.py refresh-cache")

    os.environ.setdefault("HYBRID_SEARCH_ENABLED", "1")
    search_config = load_search_config_from_schedule(CONFIG, SCHEDULE)
    wf = load_workflow_config()

    lines = [
        "Local @bot Q&A test (no Feishu messages sent)",
        f"workflow_configured={wf is not None}",
        f"hybrid_enabled={os.getenv('HYBRID_SEARCH_ENABLED', '1')}",
        "",
    ]

    for query in QUERIES:
        display_q = query or "(empty)"
        lines.append("=" * 60)
        lines.append(f"QUERY: {display_q}")

        if not query.strip():
            lines.append("RESULT: skip (empty query -> bot would ask for keywords)")
            lines.append("")
            continue

        try:
            answer = answer_query(query, search_config=search_config)
            preview = answer.reply[:800].replace("\r\n", "\n")
            if len(answer.reply) > 800:
                preview += "\n...(truncated)"
            lines.extend([
                f"match_mode={answer.match_mode}",
                f"events={len(answer.events)}",
                f"cache_total_in_window={answer.cache_total_in_window}",
                f"reply_chars={len(answer.reply)}",
                "--- reply preview ---",
                preview,
                "",
            ])
            if answer.events:
                lines.append("top_events:")
                for i, e in enumerate(answer.events[:3], 1):
                    lines.append(f"  {i}. [{e.source}] {e.name[:55]}")
                lines.append("")
        except Exception as exc:
            lines.append(f"ERROR: {type(exc).__name__}: {exc}")
            lines.append("")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
