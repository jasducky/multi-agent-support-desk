"""The terminal front end (Stage 4): log in, then render each pipeline event as one line.

  ./run.sh chat                       interactive, hidden password (C-1, C-2)
  python -m support.cli --user EMAIL --password PW --events    raw NDJSON only (C-3)

It only renders; the turn itself is support/pipeline.py (P-1).
"""

import argparse
import asyncio
import getpass
import json
import os
import sys
import urllib.request

from dotenv import load_dotenv

from support.pipeline import SupportPipeline

SPEED_TARGET_MS = 8000  # T-LAT-P50 in THRESHOLDS.md


def _secs(ms: int) -> str:
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"


def render(event: dict) -> str | None:
    """One readable line per event, in the style sketched in BUILD_LOG Stage 4."""
    kind = event["type"]
    if kind == "trace":
        return None  # printed after the turn instead (O-5)
    if kind == "stage":
        return None  # its step line says how it went
    if kind == "step":
        mark = "✓" if event["status"] == "passed" else "✗"
        return f"{mark} {event['key']:<12} {event['status']:<8} {_secs(event['ms'])}   {event.get('detail', '')}"
    if kind == "llm":
        return (f"· llm          {event['decision']}   "
                f"{event['tokens_in']}→{event['tokens_out']} tokens   {_secs(event['ms'])}")
    if kind == "tool_call":
        args = "  ".join(f"{k} {v}" for k, v in event["args"].items())
        bound = ", ".join(event["info"].get("bound", []))
        return f"→ tool         {event['name']}  {args}" + (f"  ({bound}: bound to login)" if bound else "")
    if kind == "tool_result":
        if not event["ok"]:
            return f"← result       FAILED  {event['error']}   {_secs(event['ms'])}"
        rows = event["result"] if isinstance(event["result"], list) else [event["result"]]
        rows = [r for r in rows if r]
        summary = "; ".join(
            f"order {r['order_id']}: {r['status']}" if isinstance(r, dict) and "status" in r
            else json.dumps(r) for r in rows
        ) or "nothing found"
        return f"← result       {summary}   {_secs(event['ms'])}"
    if kind == "final":
        ok = "✓" if event["wall_clock_ms"] <= SPEED_TARGET_MS else "slow"
        return f"■ final        \"{event['response']}\"   {_secs(event['wall_clock_ms'])} {ok}"
    if kind == "error":
        return f"✗ ERROR at {event['step']}: {event['error']}"
    return json.dumps(event)


# C-4: name the missing service instead of failing halfway through a turn.
SERVICES = {"Toolbox (./run.sh start)": "http://127.0.0.1:5001",
            "Phoenix (./run.sh start)": "http://localhost:6006/healthz",
            "Security Judge (./run.sh start)": "http://127.0.0.1:10002/.well-known/agent-card.json"}


def missing_services() -> list[str]:
    down = []
    for name, url in SERVICES.items():
        try:
            urllib.request.urlopen(url, timeout=2)
        except OSError:
            down.append(name)
    return down


async def main() -> None:
    parser = argparse.ArgumentParser(description="Customer support chat")
    parser.add_argument("--user", help="email (otherwise asked)")
    parser.add_argument("--password", help="demo only; otherwise asked, hidden")
    parser.add_argument("--events", action="store_true", help="print raw NDJSON events only")
    args = parser.parse_args()
    load_dotenv()
    if not os.environ.get("SKIP_SERVICE_CHECK") and (down := missing_services()):
        print("Not running: " + ", ".join(down), file=sys.stderr)
        sys.exit(1)

    async with SupportPipeline() as pipeline:
        email = args.user or input("Email: ")
        password = args.password or getpass.getpass("Password: ")  # hidden input
        user = await pipeline.log_in(email, password)
        if user is None:
            print("Invalid email or password.", file=sys.stderr)
            sys.exit(1)
        if not args.events:
            print(f"Hello {user['full_name']}. Ask about your orders ('quit' to leave).")

        while True:
            if not args.events:
                print("You: ", end="", flush=True)
            line = sys.stdin.readline()
            if not line:  # end of input (e.g. a piped message)
                break
            text = line.strip()
            if text.lower() in {"quit", "exit", "q"}:
                break
            if not text:
                continue
            url = None
            async for event in pipeline.turn(user["user_id"], text):
                if args.events:
                    print(json.dumps(event), flush=True)
                    continue
                if event["type"] == "trace":
                    url = event["url"]
                if (shown := render(event)) is not None:
                    print(shown, flush=True)
            if url and not args.events:
                print(f"  trace        {url}")


if __name__ == "__main__":
    asyncio.run(main())
