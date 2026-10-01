"""Copy the gold sets from EVALS.md section 3 into eval/gold/<set>.jsonl, one row per line.

Parsed, not retyped, so the sets can't drift from EVALS.md. Re-run if EVALS.md changes:
  python -m eval.transcribe_gold
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETS = {"3.1": "attack", "3.2": "legit", "3.3": "offtopic", "3.4": "probe",
        "3.5": "order", "3.6": "action", "3.7": "memory"}


def _cells(line: str) -> list[str]:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return [c[1:-1] if len(c) > 1 and c.startswith("`") and c.endswith("`") else c for c in cells]


def main() -> None:
    text = (ROOT / "EVALS.md").read_text()
    section = text.split("## 3. The gold sets", 1)[1].split("\n## 4.", 1)[0]
    out = ROOT / "eval" / "gold"
    out.mkdir(parents=True, exist_ok=True)
    for number, name in SETS.items():
        block = re.split(rf"\n### {re.escape(number)} ", section, maxsplit=1)[1].split("\n### ", 1)[0]
        lines = [l for l in block.splitlines() if l.startswith("|")]
        header = [h.lower().replace(" ", "_") for h in _cells(lines[0])]
        rows = [dict(zip(header, _cells(l))) for l in lines[2:] if re.match(r"\|\s*[A-Z]\d\d", l)]
        with open(out / f"{name}.jsonl", "w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{name:<9} {len(rows):>3} rows  columns: {', '.join(header)}")


if __name__ == "__main__":
    main()
