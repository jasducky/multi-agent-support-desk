"""The pipeline (Stage 4): the one module that runs a turn and yields its events (SPEC 7.1, P-1).

The CLI and the web server only render what this yields. Each turn also writes
runs/<turn_id>.json (EVALS 4.1) before its last event.

Steps, in the order P-2 fixes: sanitize -> judge -> guardrail -> recall -> agent -> mask -> save. A block ends the turn at once (P-3); a guard that fails ends
it with an error naming the step, never with "allow" (P-4).
"""

import json
import logging
import time
import uuid
import warnings
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import yaml
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from toolbox_core import ToolboxClient

from guards import sanitizer
from guards.guardrail import BLOCK_REPLIES, Guardrail
from guards.guardrail import PROMPT_VERSION as GUARDRAIL_VERSION
from support import telemetry
from support.memory import Memory
from support.agent import MODEL, PROMPT_VERSION, build_agent

# ADK announces that it describes tools to Gemini in a newer, "experimental" way. Harmless.
warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*")
# google-genai logs a long advisory about its automatic function calling on every Guardrail call.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=DeprecationWarning)  # library-internal notices

ROOT = Path(__file__).resolve().parent.parent
TOOLBOX_URL = "http://127.0.0.1:5001"
APP_NAME = "customer_support"
BOUND = ("customer_email", "user_email")  # filled in from the log-in, never by the model (M-5)
JUDGE_URL = "http://127.0.0.1:10002/"
MASKER_URL = "http://127.0.0.1:10003/"
GUARD_TIMEOUT_S = 15
BLOCKED_REPLY = "Sorry, I can't help with that message. I can help with your orders, deliveries, returns and account."


class GuardError(Exception):
    """A guard could not give a verdict: unreachable, timed out, or an answer we can't read."""


async def _a2a(url: str, name: str, text: str) -> dict:
    """One A2A `message/send` call (J-1, K-1). Returns the service's JSON answer."""
    request = {
        "jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
        "params": {"message": {"role": "user", "messageId": uuid.uuid4().hex,
                               "parts": [{"kind": "text", "text": text}]}},
    }
    try:
        async with httpx.AsyncClient(timeout=GUARD_TIMEOUT_S) as client:
            reply = (await client.post(url, json=request)).json()
    except httpx.TimeoutException:
        raise GuardError(f"{name} timed out after {GUARD_TIMEOUT_S}s")
    except (httpx.HTTPError, ValueError) as exc:
        raise GuardError(f"{name} unreachable: {type(exc).__name__}: {exc}")
    try:
        answer = reply["result"]["artifacts"][-1]["parts"][0]["text"]
        return json.loads(answer.strip().removeprefix("```json").removesuffix("```"))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GuardError(f"{name} gave no readable answer: {str(reply)[:200]}") from exc


async def ask_judge(message: str) -> tuple[str, str]:
    """The Security Judge's verdict: (allow | block, reason) (J-3)."""
    verdict = await _a2a(JUDGE_URL, "Security Judge", message)
    if verdict.get("verdict") not in ("allow", "block") or not verdict.get("reason"):
        raise GuardError(f"Security Judge gave no readable verdict: {verdict}")
    return verdict["verdict"], verdict["reason"]


async def ask_masker(reply: str, email: str) -> dict:
    """The Data Masker's answer: masked text plus what it changed (K-1, K-3)."""
    answer = await _a2a(MASKER_URL, "Data Masker", json.dumps({"text": reply, "user_email": email}))
    if not isinstance(answer.get("masked_text"), str) or "count" not in answer:
        raise GuardError(f"Data Masker gave no readable answer: {answer}")
    return answer


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
        self._guardrail = Guardrail()
        self._memory = Memory()

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
        return {"user_id": email, "full_name": found["full_name"],
                "is_premium": bool(found.get("is_premium"))}

    def is_logged_in(self, email: str) -> bool:
        return email in self._runners

    def log_out(self, email: str) -> None:
        self._runners.pop(email, None)

    async def db_ok(self) -> str:
        """For /health: a log-in check with no real customer reaches the database, returns nothing."""
        try:
            check_login = await self._toolbox.load_tool("check-login")
            await check_login(email="health@check.invalid", password="-")
            return "ok"
        except Exception as e:  # noqa: BLE001 - /health reports any failure as a string
            return f"error: {type(e).__name__}"

    async def mem0_ok(self) -> str:
        try:
            await self._memory.all("health@check.invalid")
            return "ok"
        except Exception as e:  # noqa: BLE001
            return f"error: {type(e).__name__}"

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
            "session.id": session_id, "metadata": json.dumps({"prompt_version": PROMPT_VERSION,
                                    "guardrail_version": GUARDRAIL_VERSION}),
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

        def finish(status: str, key: str | None = None, error: str | None = None,
                   reply: str = BLOCKED_REPLY) -> list[dict]:
            """The turn's last event, after writing its run file. Blocked and error turns."""
            record.update(terminated=status, blocked_at=key if status == "blocked" else None,
                          wall_clock_ms=ms_since(started))
            if error:  # A2: an error turn says why in its run log, not only in the stream
                record["error"] = f"{key}: {error}"
            self._write_run(record)
            if status == "error":
                span.set_status(Status(StatusCode.ERROR, error))
                return [{"type": "error", "step": key, "status": 502, "error": error,
                         "terminated": "error"}]
            span.set_attribute("output.value", reply)
            return [{"type": "final", "blocked": True, "blocked_at": key,
                     "response": reply, "terminated": "blocked",
                     "wall_clock_ms": record["wall_clock_ms"], "tokens": record["tokens"]}]

        def step(key: str, passed: bool, detail: str, ms: int, span_name: str, kind: str) -> dict:
            status = "passed" if passed else "blocked"
            record["steps"].append({"key": key, "status": status, "ms": ms})
            return {"type": "step", "key": key, "status": status, "detail": detail, "ms": ms,
                    "span": span_name, "kind": kind}

        # 1. Sanitizer: in-process code, no model (S-1).
        yield {"type": "stage", "key": "sanitize", "label": "Sanitizer"}
        t = time.monotonic()
        with self._tracer.start_as_current_span("security.sanitize", attributes={
                "openinference.span.kind": "GUARDRAIL", "input.value": message}) as s:
            passed, detail = sanitizer.check(message)
            s.set_attribute("output.value", ("pass: " if passed else "block: ") + detail)
        yield step("sanitize", passed, detail, ms_since(t), "security.sanitize", "Python fn")
        if not passed:
            for e in finish("blocked", "sanitize"):
                yield e
            return

        # 2. Security Judge: its own service, over A2A (J-1 to J-4).
        yield {"type": "stage", "key": "judge", "label": "A2A Security Judge"}
        t = time.monotonic()
        with self._tracer.start_as_current_span("security.a2a_judge", attributes={
                "openinference.span.kind": "GUARDRAIL", "input.value": message}) as s:
            try:
                verdict, reason = await ask_judge(message)
                s.set_attribute("output.value", json.dumps({"verdict": verdict, "reason": reason}))
                failure = None
            except GuardError as exc:
                s.set_status(Status(StatusCode.ERROR, str(exc)))
                s.record_exception(exc)
                failure = str(exc)
        if failure:
            record["steps"].append({"key": "judge", "status": "error", "ms": ms_since(t)})
            for e in finish("error", "judge", failure):
                yield e
            return
        yield step("judge", verdict == "allow", f"{verdict}: {reason}", ms_since(t),
                   "security.a2a_judge", "A2A")
        if verdict == "block":
            for e in finish("blocked", "judge"):
                yield e
            return

        # 3. Guardrail: in-process agent, is this something the shop's desk should handle (GR-1)?
        yield {"type": "stage", "key": "guardrail", "label": "Guardrail (on-topic check)"}
        t = time.monotonic()
        with self._tracer.start_as_current_span("guardrail.check", attributes={
                "openinference.span.kind": "GUARDRAIL", "input.value": message}) as s:
            try:
                answer = await self._guardrail.check(message)
                s.set_attribute("output.value", json.dumps(answer))
                failure = None
            except Exception as exc:  # GR-4: unreadable or failed is an error, never a pass
                s.set_status(Status(StatusCode.ERROR, str(exc)))
                s.record_exception(exc)
                failure = f"Guardrail failed: {exc}"
        if failure:
            record["steps"].append({"key": "guardrail", "status": "error", "ms": ms_since(t)})
            for e in finish("error", "guardrail", failure):
                yield e
            return
        safe = answer["decision"] == "safe"
        detail = answer["decision"] + ("" if safe else f" ({answer['block_type']})") + f": {answer['reasoning']}"
        yield step("guardrail", safe, detail, ms_since(t), "guardrail.check", "in-process")
        if not safe:
            for e in finish("blocked", "guardrail", reply=BLOCK_REPLIES[answer["block_type"]]):
                yield e
            return

        # 4. Recall: a pipeline step, not a tool (R-1, R-6).
        yield {"type": "stage", "key": "recall", "label": "Memory recall (Mem0)"}
        t = time.monotonic()
        with self._tracer.start_as_current_span("memory.recall", attributes={
                "openinference.span.kind": "RETRIEVER", "input.value": message}) as s:
            try:
                memories = await self._memory.recall(email, message)
                for i, m in enumerate(memories):
                    s.set_attribute(f"retrieval.documents.{i}.document.content", m["memory"])
                    s.set_attribute(f"retrieval.documents.{i}.document.score", m["score"])
                failure = None
            except Exception as exc:
                s.set_status(Status(StatusCode.ERROR, str(exc)))
                s.record_exception(exc)
                failure = f"Memory recall failed: {type(exc).__name__}: {exc}"
        if failure:
            record["steps"].append({"key": "recall", "status": "error", "ms": ms_since(t)})
            for e in finish("error", "recall", failure):
                yield e
            return
        inserted = sum(m["inserted"] for m in memories)
        ms = ms_since(t)
        record["steps"].append({"key": "recall", "status": "passed", "ms": ms,
                                "inserted": inserted, "skipped": len(memories) - inserted})
        yield {"type": "step", "key": "recall", "status": "passed", "ms": ms,
               "detail": f"{inserted} used, {len(memories) - inserted} skipped",
               "span": "memory.recall", "kind": "Python fn",
               "memories": [{k: m[k] for k in ("memory", "score", "inserted", "reason")} for m in memories]}

        # 5. The support agent.
        yield {"type": "stage", "key": "agent", "label": "Support agent (ADK, tools over MCP)"}
        agent_started = last_llm_start = time.monotonic()
        call_ids: dict[str, tuple[int, float]] = {}  # ADK's call id -> (our id, when it was called)
        response = ""
        try:
            agent_input = Memory.as_prompt(memories, message)  # R-3: memories above the message
            new_message = types.Content(role="user", parts=[types.Part(text=agent_input)])
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
            record.update(terminated="error", wall_clock_ms=ms_since(started),
                          error=f"agent: {type(exc).__name__}: {exc}")
            self._write_run(record)
            yield {"type": "error", "step": "agent", "status": 502,
                   "error": f"{type(exc).__name__}: {exc}", "terminated": "error"}
            return

        yield {"type": "step", "key": "agent", "status": "passed", "detail": "answered",
               "ms": ms_since(agent_started), "span": "invoke_agent", "kind": "in-process"}

        # 6. Data Masker: its own service, over A2A (K-1 to K-3).
        yield {"type": "stage", "key": "mask", "label": "A2A Data Masker"}
        t = time.monotonic()
        with self._tracer.start_as_current_span("security.a2a_mask", attributes={
                "openinference.span.kind": "GUARDRAIL", "input.value": response}) as s:
            try:
                masked = await ask_masker(response, email)
                s.set_attribute("output.value", json.dumps(masked))
                failure = None
            except GuardError as exc:
                s.set_status(Status(StatusCode.ERROR, str(exc)))
                s.record_exception(exc)
                failure = str(exc)
        if failure:  # never show an unmasked reply
            record["steps"].append({"key": "mask", "status": "error", "ms": ms_since(t)})
            for e in finish("error", "mask", failure):
                yield e
            return
        response = masked["masked_text"]
        detail = ("masked " + ", ".join(masked["changes"])) if masked["count"] else "nothing to mask"
        yield step("mask", True, detail, ms_since(t), "security.a2a_mask", "A2A")

        # 7. Save: the customer's own message only, never the reply (R-4).
        yield {"type": "stage", "key": "save", "label": "Memory save (Mem0)"}
        t = time.monotonic()
        with self._tracer.start_as_current_span("memory.save", attributes={
                "openinference.span.kind": "TOOL", "input.value": message}) as s:
            try:
                status = await self._memory.save(email, message)
                s.set_attribute("output.value", status)
                failure = None
            except Exception as exc:
                s.set_status(Status(StatusCode.ERROR, str(exc)))
                s.record_exception(exc)
                failure = f"Memory save failed: {type(exc).__name__}: {exc}"
        if failure:
            record["steps"].append({"key": "save", "status": "error", "ms": ms_since(t)})
            for e in finish("error", "save", failure):
                yield e
            return
        yield step("save", True, f"your message sent to Mem0 ({status})", ms_since(t),
                   "memory.save", "Python fn")

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
