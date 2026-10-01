"""The pipeline (Stage 4): the one module that runs a turn and yields its events (SPEC 7.1, P-1).

The CLI and the web server only render what this yields. Each turn also writes
runs/<turn_id>.json (EVALS 4.1) before its last event.

So far the turn has one step, `agent`. Later stages add sanitize, judge, guardrail, recall,
mask and save around it, in the order P-2 fixes.
"""

import json
import time
import uuid
import warnings
from collections.abc import AsyncIterator
from pathlib import Path

import yaml
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from toolbox_core import ToolboxClient

from support import telemetry
from support.agent import MODEL, PROMPT_VERSION, build_agent

# ADK announces that it describes tools to Gemini in a newer, "experimental" way. Harmless.
warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*")

ROOT = Path(__file__).resolve().parent.parent
TOOLBOX_URL = "http://127.0.0.1:5001"
APP_NAME = "customer_support"
BOUND = ("customer_email", "user_email")  # filled in from the log-in, never by the model (M-5)


def _tool_info() -> dict:
    """What each tool is, read from tools.yaml, for the tool_call event's `info` (SPEC 7.1)."""
    config = yaml.safe_load((ROOT / "mcp_toolbox" / "tools.yaml").read_text())
    info = {}
    for name, tool in config["tools"].items():
        statement = " ".join(tool["statement"].split())
        info[name] = {
            "kind": "MCP",
            "access": "WRITE" if statement.upper().find("INSERT") >= 0 else "READ",
            "statement": statement,
            "params": [p["name"] for p in tool.get("parameters", [])],  # in $1, $2 ... order
            "bound": [p["name"] for p in tool.get("parameters", []) if p["name"] in BOUND],
        }
    return info


def _decode(value):
    """Turn a JSON string into the object it holds; leave anything else as it is."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _unwrap(response) -> object:
    """The Toolbox wraps a tool's output as {"result": "<JSON string>"}; return what is inside."""
    if isinstance(response, dict) and set(response) == {"result"}:
        return _decode(response["result"])
    return response


class SupportPipeline:
    """Holds the Toolbox connection and one agent session per logged-in customer."""

    def __init__(self, toolbox_url: str = TOOLBOX_URL):
        self._tracer = telemetry.set_up()  # before any agent is built (Stage 5)
        self._toolbox = ToolboxClient(toolbox_url)
        self._sessions = InMemorySessionService()
        self._runners: dict[str, tuple[Runner, str]] = {}  # email -> (runner, session id)
        self._tool_info = _tool_info()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._toolbox.close()

    async def log_in(self, email: str, password: str) -> dict | None:
        """check-login answers with the customer's name or nothing; the password never comes back."""
        email = email.strip().lower()
        check_login = await self._toolbox.load_tool("check-login")  # not in the agent's toolset
        found = _decode(await check_login(email=email, password=password) or "null")
        if isinstance(found, list):  # one row can come back as a row or as a list of one
            found = found[0] if found else None
        if not found:
            return None
        # M-5: the toolset is loaded with this customer's email bound.
        tools = await self._toolbox.load_toolset(
            "support_agent_tools", bound_params={name: email for name in BOUND}
        )
        session = await self._sessions.create_session(app_name=APP_NAME, user_id=email)
        runner = Runner(agent=build_agent(tools), app_name=APP_NAME, session_service=self._sessions)
        self._runners[email] = (runner, session.id)
        return {"user_id": email, "full_name": found["full_name"]}

    async def turn(self, email: str, message: str) -> AsyncIterator[dict]:
        """Run one turn and yield its events, in order. The last event is `final` or `error`."""
        runner, session_id = self._runners[email]
        turn_id = f"turn_{time.strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:6]}"
        started = time.monotonic()
        record = {
            "turn_id": turn_id, "trace_id": None, "user": email, "message": message,
            "terminated": None, "blocked_at": None, "wall_clock_ms": None,
            "tokens": {"in": 0, "out": 0}, "steps": [], "tool_calls": [], "llm_calls": 0,
        }

        # O-2: one root span per turn; everything below runs inside it, so ADK's invoke_agent,
        # call_llm and execute_tool spans become its children.
        span = self._tracer.start_span("agent.turn", attributes={
            "openinference.span.kind": "CHAIN", "input.value": message, "user.id": email,
            "session.id": session_id, "metadata": json.dumps({"prompt_version": PROMPT_VERSION}),
        })
        token = otel_context.attach(trace.set_span_in_context(span))
        try:
            async for event in self._run_turn(runner, session_id, email, message, turn_id,
                                              started, record, span):
                yield event
        finally:
            otel_context.detach(token)
            span.end()

    async def _run_turn(self, runner, session_id, email, message, turn_id, started, record, span):
        def ms_since(t: float) -> int:
            return round((time.monotonic() - t) * 1000)

        trace_id = format(span.get_span_context().trace_id, "032x")
        record["trace_id"] = trace_id
        yield {"type": "trace", "turn_id": turn_id, "trace_id": trace_id,
               "url": telemetry.trace_url(trace_id)}

        yield {"type": "stage", "key": "agent", "label": "Support agent (ADK, tools over MCP)"}
        agent_started = last_llm_start = time.monotonic()
        call_ids: dict[str, tuple[int, float]] = {}  # ADK's call id -> (our id, when it was called)
        response = ""
        try:
            new_message = types.Content(role="user", parts=[types.Part(text=message)])
            async for event in runner.run_async(
                user_id=email, session_id=session_id, new_message=new_message
            ):
                calls = event.get_function_calls()
                results = event.get_function_responses()

                # A model reply: either "call a tool" or the final answer.
                if event.author != "user" and not results and event.content:
                    usage = event.usage_metadata
                    tokens_in = (usage.prompt_token_count or 0) if usage else 0
                    tokens_out = (usage.candidates_token_count or 0) if usage else 0
                    record["tokens"]["in"] += tokens_in
                    record["tokens"]["out"] += tokens_out
                    record["llm_calls"] += 1
                    decision = (
                        "call " + ", ".join(c.name for c in calls) if calls else "final answer"
                    )
                    yield {
                        "type": "llm", "model": MODEL, "decision": decision,
                        "tokens_in": tokens_in, "tokens_out": tokens_out,
                        "ms": ms_since(last_llm_start), "span": "call_llm",
                    }

                for call in calls:
                    our_id = len(call_ids) + 1
                    call_ids[call.id] = (our_id, time.monotonic())
                    yield {
                        "type": "tool_call", "id": our_id, "name": call.name,
                        "args": {k: _decode(v) for k, v in (call.args or {}).items()},
                        "info": self._tool_info.get(call.name, {"kind": "MCP"}),
                        "span": f"execute_tool {call.name}",
                    }

                for result in results:
                    our_id, called_at = call_ids.get(result.id, (len(call_ids), started))
                    output = _unwrap(result.response)
                    error = output.get("error") if isinstance(output, dict) else None
                    ms = ms_since(called_at)
                    record["tool_calls"].append(
                        {"name": result.name, "ok": error is None, "ms": ms}
                        | ({"error": error} if error else {})
                    )
                    yield {
                        "type": "tool_result", "id": our_id, "name": result.name,
                        "ok": error is None, "ms": ms, "result": output,
                    } | ({"error": error} if error else {})
                    last_llm_start = time.monotonic()  # the model is asked again now

                if event.is_final_response() and event.content and event.content.parts:
                    response = "".join(p.text or "" for p in event.content.parts if p.text)

        except Exception as exc:  # fail loud: the turn ends with an error naming the step
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            record.update(terminated="error", wall_clock_ms=ms_since(started))
            self._write_run(record)
            yield {"type": "error", "step": "agent", "status": 502,
                   "error": f"{type(exc).__name__}: {exc}", "terminated": "error"}
            return

        yield {"type": "step", "key": "agent", "status": "passed", "detail": "answered",
               "ms": ms_since(agent_started), "span": "invoke_agent", "kind": "in-process"}

        span.set_attribute("output.value", response)
        record.update(terminated="done", wall_clock_ms=ms_since(started))
        self._write_run(record)
        yield {"type": "final", "blocked": False, "blocked_at": None, "response": response,
               "terminated": "done", "wall_clock_ms": record["wall_clock_ms"],
               "tokens": record["tokens"]}

    @staticmethod
    def _write_run(record: dict) -> None:
        """runs/<turn_id>.json, written before the turn's last event (EVALS 4.1)."""
        runs = ROOT / "runs"
        runs.mkdir(exist_ok=True)
        (runs / f"{record['turn_id']}.json").write_text(json.dumps(record, indent=2))
