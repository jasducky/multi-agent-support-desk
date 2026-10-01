"""Print one trace's spans as a tree, read back from Phoenix (Stage 5 check).

  python -m support.span_tree <trace_id>           the tree, with span kinds and times
  python -m support.span_tree <trace_id> --count   how many spans Phoenix holds for it
"""

import json
import sys
import urllib.request
from datetime import datetime

from support.telemetry import PHOENIX, PROJECT


def spans_for(trace_id: str) -> list[dict]:
    found, cursor = [], None
    while True:
        url = f"{PHOENIX}/v1/projects/{PROJECT}/spans?limit=1000" + (f"&cursor={cursor}" if cursor else "")
        with urllib.request.urlopen(url) as r:
            page = json.load(r)
        found += [s for s in page["data"] if s["context"]["trace_id"] == trace_id]
        cursor = page.get("next_cursor")
        if not cursor:
            return found


def _ms(span: dict) -> int:
    start, end = (datetime.fromisoformat(span[k]) for k in ("start_time", "end_time"))
    return round((end - start).total_seconds() * 1000)


def main() -> None:
    trace_id = sys.argv[1]
    spans = spans_for(trace_id)
    if "--count" in sys.argv:
        print(f"Phoenix holds {len(spans)} spans for trace {trace_id}")
        return
    children: dict[str | None, list[dict]] = {}
    ids = {s["context"]["span_id"] for s in spans}
    for s in sorted(spans, key=lambda s: s["start_time"]):
        parent = s.get("parent_id") if s.get("parent_id") in ids else None
        children.setdefault(parent, []).append(s)

    def show(span: dict, depth: int) -> None:
        kind = (span.get("attributes") or {}).get("openinference.span.kind", span.get("span_kind", ""))
        label = "    " * depth + ("└─ " if depth else "") + span["name"]
        print(f"{label:<52} {kind:<10} {_ms(span):>6} ms")
        for child in children.get(span["context"]["span_id"], []):
            show(child, depth + 1)

    roots = children.get(None, [])
    for root in roots:
        show(root, 0)
    if len(roots) != 1:
        print(f"⚠️  {len(roots)} root spans: expected exactly one (agent.turn)")


if __name__ == "__main__":
    main()
