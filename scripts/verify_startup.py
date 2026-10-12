"""Verify scrape + cache after refresh (no Feishu send)."""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "logs" / "startup_check.txt"
DB = ROOT / "data" / "events.db"


def main() -> None:
    if not DB.exists():
        raise SystemExit("events.db missing")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT source, name, location, start_date, embedding IS NOT NULL AS has_emb FROM events").fetchall()
    conn.close()

    by_source = Counter(r["source"] for r in rows)
    with_emb = sum(1 for r in rows if r["has_emb"])
    bad = [
        r for r in rows
        if any(x in f"{r['name']} {r['location']}" for x in ("成都", "上海"))
        and "上海街" not in f"{r['name']} {r['location']}"
    ]

    lines = [
        f"total={len(rows)}",
        f"by_source={dict(by_source)}",
        f"embeddings={with_emb}/{len(rows)}",
        f"non_gba_check={'FAIL ' + str([(r['source'], r['name'][:40]) for r in bad[:5]]) if bad else 'PASS'}",
        "",
        "sample_by_source:",
    ]
    for source in ("hktdc", "zhandaren", "discoverhongkong", "scmp"):
        samples = [r for r in rows if r["source"] == source][:3]
        lines.append(f"  [{source}] count={by_source.get(source, 0)}")
        for r in samples:
            lines.append(f"    - {r['start_date']} | {r['name'][:50]} | {str(r['location'])[:30]}")

    # Push pool preview (no send)
    import yaml
    from src.scraper.service import prepare_push_events

    msg = next(
        s["message"]
        for s in yaml.safe_load((ROOT / "config" / "schedules.yaml").read_text(encoding="utf-8"))["schedules"]
        if s["name"] == "weekly-hk-events"
    )
    push_events = prepare_push_events(msg, mark_seen=False)
    push_by_source = Counter(e.source for e in push_events)
    lines.extend([
        "",
        f"push_preview(max={msg.get('max_items')}, only_new={msg.get('only_new')})={len(push_events)}",
        f"push_by_source={dict(push_by_source)}",
    ])
    for i, e in enumerate(push_events[:5], 1):
        lines.append(f"  {i}. [{e.source}] {e.name[:55]}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
