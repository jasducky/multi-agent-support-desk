"""Error analysis page for eval runs (open coding, axial coding, count), on port 8001. A reviewing tool, not part of the product.

Phoenix shows whether code ran; it cannot show whether an answer was right. This page joins the
two: each eval item from a report (pass or fail, and why), with its turn rebuilt from its Phoenix
trace (guards, memories with scores, every tool call with what went in and came out, the reply),
and a place to write what went wrong. Notes are saved to eval/review-notes-<run>.json.

Run: ./run.sh review   (then open http://localhost:8001)
"""

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from eval import run as runner
from support import memory as memory_settings

ROOT = Path(__file__).resolve().parent.parent
RUNS = {"run1": ROOT / "reports" / "run1" / "eval.json", "latest": ROOT / "reports" / "eval.json"}
EXPECTED = {"order": lambda r: f"reply contains '{r['must_contain']}', tool: {r['expected_tool']}",
            "action": lambda r: f"one action-log call, type {r['expected_`action_type`']}",
            "memory": lambda r: f"a used memory contains '{r['keyword']}'",
            "attack": lambda r: "blocked by a guard", "offtopic": lambda r: "blocked by a guard",
            "legit": lambda r: "answered, not blocked", "probe": lambda r: "no other customer's data"}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _gold() -> dict:
    return {(name, r["id"]): r for name in EXPECTED for r in runner.rows(name)}


def _notes_file(run: str) -> Path:
    return ROOT / "eval" / f"review-notes-{run}.json"


@app.get("/")
async def page():
    return FileResponse(ROOT / "eval" / "review.html", media_type="text/html")


@app.get("/api/runs")
async def runs():
    out = []
    for name, path in RUNS.items():
        if path.exists():
            rep = json.loads(path.read_text())
            out.append({"run": name, "ran_at": rep["ran_at"], "commit": rep["commit"]})
    return out


@app.get("/api/items")
async def items(run: str = "run1"):
    rep = json.loads(RUNS[run].read_text())
    gold = _gold()
    out = []
    for i in rep["items"]:
        row = gold.get((i["set"], i["id"]), {})
        out.append({"id": i["id"], "set": i["set"], "user": i["user"], "pass": i.get("pass"),
                    "why": i.get("why"), "terminated": i["terminated"], "blocked_at": i["blocked_at"],
                    "ms": i["ms"], "trace_id": i["trace_id"],
                    "expected": EXPECTED[i["set"]](row) if row else ""})
    return out


def _flat(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def _json(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return text
    if isinstance(value, dict) and set(value) == {"result"}:
        return _json(value["result"])
    if isinstance(value, dict):
        return {k: _json(v) if isinstance(v, str) and v[:1] in "[{" else v for k, v in value.items()}
    return value


@app.get("/api/trace/{trace_id}")
async def trace(trace_id: str):
    spans = runner.fetch_spans({trace_id}).get(trace_id, [])
    spans.sort(key=lambda s: s["start_time"])
    turn = {"question": None, "reply": None, "guards": [], "recall": [], "tools": [], "llm_calls": 0,
            "mask": None, "save": None, "errors": []}
    for s in spans:
        a, name = _flat(s.get("attributes", {})), s["name"]
        if s.get("status_code") == "ERROR":
            turn["errors"].append(f"{name}: {s.get('status_message')}")
        if name == "agent.turn":
            turn["question"], turn["reply"] = a.get("input.value"), a.get("output.value")
        elif name in ("security.sanitize", "security.a2a_judge", "guardrail.check"):
            turn["guards"].append({"name": {"security.sanitize": "sanitize", "security.a2a_judge": "judge",
                                            "guardrail.check": "guardrail"}[name],
                                   "verdict": _json(a.get("output.value"))})
        elif name == "memory.recall":
            n = 0
            while f"retrieval.documents.{n}.document.content" in a:
                text = a[f"retrieval.documents.{n}.document.content"]
                score = float(a[f"retrieval.documents.{n}.document.score"])
                turn["recall"].append({"memory": text, "score": score,
                                       "used": score >= memory_settings.MIN_SCORE
                                       and len(text) <= memory_settings.MAX_CHARS})
                n += 1
        elif name == "call_llm" and any(p["context"]["span_id"] == s["parent_id"] for p in spans
                                         if p["name"].startswith("invoke_agent support")):
            turn["llm_calls"] += 1
        elif name.startswith("execute_tool "):
            turn["tools"].append({"name": name.removeprefix("execute_tool "),
                                  "args": _json(a.get("gcp.vertex.agent.tool_call_args")),
                                  "result": _json(a.get("gcp.vertex.agent.tool_response"))})
        elif name == "security.a2a_mask":
            turn["mask"] = _json(a.get("output.value"))
        elif name == "memory.save":
            turn["save"] = a.get("output.value")
    return turn


@app.get("/api/notes")
async def get_notes(run: str = "run1"):
    f = _notes_file(run)
    return json.loads(f.read_text()) if f.exists() else {}


@app.post("/api/notes")
async def save_note(request: Request, run: str = "run1"):
    body = await request.json()
    f = _notes_file(run)
    notes = json.loads(f.read_text()) if f.exists() else {}
    notes[body["id"]] = {"note": body.get("note", ""), "type": body.get("type", "")}
    f.write_text(json.dumps(notes, indent=2, ensure_ascii=False))
    return JSONResponse({"ok": True})
