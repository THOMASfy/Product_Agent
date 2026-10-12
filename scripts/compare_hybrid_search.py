"""Compare BM25-only vs Hybrid search on sample queries."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "logs" / "hybrid_compare.txt"

QUERIES = [
    "请推荐大湾区科技展会",
    "智能硬件 展览",
    "养老 健康",
    "我们是一家电子通信企业想参展",
    "香港书展",
    "数据中心 算力",
]


def _run_queries(*, hybrid: bool) -> dict[str, list[tuple[str, str]]]:
    os.environ["HYBRID_SEARCH_ENABLED"] = "1" if hybrid else "0"
    from importlib import reload

    import src.embedding_service as embedding_service
    import src.event_cache as event_cache
    import src.hybrid_search as hybrid_search

    reload(embedding_service)
    reload(hybrid_search)
    reload(event_cache)

    from src.event_cache import EventCache

    cache = EventCache()
    try:
        results: dict[str, list[tuple[str, str]]] = {}
        for query in QUERIES:
            answer = cache.search(query, limit=5)
            results[query] = [
                (event.name[:60], answer.match_mode) for event in answer.events
            ]
        return results
    finally:
        cache.close()


def main() -> None:
    if not (ROOT / "data" / "events.db").exists():
        raise SystemExit("events.db missing; run: python main.py refresh-cache")

    bm25 = _run_queries(hybrid=False)
    hybrid = _run_queries(hybrid=True)

    lines = ["Hybrid search comparison (top 5 per query)", ""]
    for query in QUERIES:
        lines.append(f"## {query}")
        lines.append("[BM25 only]")
        if bm25[query]:
            for index, (name, mode) in enumerate(bm25[query], start=1):
                lines.append(f"  {index}. ({mode}) {name}")
        else:
            lines.append("  (no results)")
        lines.append("[Hybrid]")
        if hybrid[query]:
            for index, (name, mode) in enumerate(hybrid[query], start=1):
                lines.append(f"  {index}. ({mode}) {name}")
        else:
            lines.append("  (no results)")

        bm25_names = [item[0] for item in bm25[query]]
        hybrid_names = [item[0] for item in hybrid[query]]
        if bm25_names == hybrid_names:
            lines.append("=> order: SAME")
        elif set(bm25_names) == set(hybrid_names):
            lines.append("=> order: REORDERED")
        else:
            lines.append("=> order: DIFFERENT SET")
        lines.append("")

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
