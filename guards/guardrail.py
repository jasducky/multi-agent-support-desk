"""The Guardrail (Stage 7): is this message something this shop's support desk should handle?

An in-process ADK agent (GR-1). Its prompt is built from Julia's rule and her own six
examples in BUILD_LOG Stage 7, not from the test set (GR-2). Every check gets a fresh session,
deleted afterwards, so one verdict can't colour the next (GR-3). An answer we can't read is an
error, never a pass (GR-4).
"""

import json
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

PROMPT_VERSION = "guardrail-v1"  # words from PRD.md line 18 and SPEC.md GR-2

INSTRUCTION = """\
You check messages sent to the support desk of an online shop. Decide one thing: is this
something the shop's support desk should handle?

SAFE: anything about the customer's dealings with this shop: where an order is, what they
paid, whether a return went through, cancelling or returning something, how they like
deliveries handled, complaints and faulty items, their account and preferences. Personal
details shared to get better service are safe too. Judge what they want the shop to do, not
the words they use.

UNSAFE: using the chat as a general assistant. General questions, opinions, trivia, writing
tasks, homework, and advice on setting up or using a product.

Examples:
"Can I change the delivery date on my chair order?" -> safe
"My keyboard arrived broken, I'd like to return it." -> safe
"I've moved house, so please send everything to my new address from now on." -> safe
"Give me a recipe for a quick weeknight dinner." -> unsafe, off_topic
"Write me a strategy brief for my team." -> unsafe, off_topic
"Can you walk me through setting up my VR headset?" -> unsafe, product_setup

Reply with ONLY this JSON:
{"decision": "safe" or "unsafe", "reasoning": "<one short sentence>",
 "block_type": null, "off_topic" or "product_setup"}
"""

# What the customer sees on a block: fixed text, not written by the model (Julia's decision).
BLOCK_REPLIES = {
    "off_topic": "Sorry, I can only help with this shop: your orders, deliveries, returns and account.",
    "product_setup": ("For help setting up or using a product, the maker's support site is the best "
                      "place. If the item is faulty, I can help you return it: just tell me the order."),
}

_APP = "guardrail"


class Guardrail:
    def __init__(self):
        self._agent = LlmAgent(name="guardrail_agent", model="gemini-2.5-flash",
                               instruction=INSTRUCTION)
        self._sessions = InMemorySessionService()
        self._runner = Runner(agent=self._agent, app_name=_APP, session_service=self._sessions)

    async def check(self, message: str) -> dict:
        """Returns {"decision", "reasoning", "block_type"}. Raises ValueError if unreadable (GR-4)."""
        user = "guardrail"
        session = await self._sessions.create_session(app_name=_APP, user_id=user,
                                                      session_id=uuid.uuid4().hex)  # GR-3
        text = ""
        try:
            content = types.Content(role="user", parts=[types.Part(text=message)])
            async for event in self._runner.run_async(user_id=user, session_id=session.id,
                                                      new_message=content):
                if event.is_final_response() and event.content and event.content.parts:
                    text = "".join(p.text or "" for p in event.content.parts if p.text)
        finally:
            await self._sessions.delete_session(app_name=_APP, user_id=user, session_id=session.id)
        try:
            answer = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
            if answer["decision"] not in ("safe", "unsafe") or not answer.get("reasoning"):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise ValueError(f"Guardrail gave no readable decision: {text[:200]!r}")
        if answer["decision"] == "unsafe" and answer.get("block_type") not in BLOCK_REPLIES:
            answer["block_type"] = "off_topic"
        return answer
