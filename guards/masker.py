"""The Data Masker (Stage 8): its own process on port 10003, reached over A2A (K-1).

Julia's decision: hide other people's emails, every phone number, and card numbers except the
last four digits. The customer's own email and address stay visible. The masking is plain code,
so it changes only those (K-2): never case, spacing or anything else. It reports what it changed,
or "nothing to mask" (K-3).

The request is JSON text: {"text": "<the agent's reply>", "user_email": "<the customer>"}.
The answer is JSON text: {"masked_text": "...", "count": n, "changes": ["1 phone number", ...]}.

Run: uvicorn guards.masker:app --host 127.0.0.1 --port 10003   (./run.sh start does this)
"""

import json
import re
import warnings

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*")

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")  # 13 to 19 digits, maybe split by spaces or dashes
# 10 to 12 digits, maybe starting with + and split by spaces, dashes, dots or brackets.
# Dates (8 digits), prices and order numbers are shorter, so they are left alone.
PHONE = re.compile(r"(?<![\w+])\+?\(?\d(?:[\d ().-]{8,16})\d\b")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def mask(text: str, user_email: str) -> dict:
    counts = {"card number": 0, "phone number": 0, "email address": 0}

    def card(m: re.Match) -> str:
        counts["card number"] += 1
        return f"[card ending {_digits(m.group(0))[-4:]}]"

    def phone(m: re.Match) -> str:
        if not 10 <= len(_digits(m.group(0))) <= 12:
            return m.group(0)
        counts["phone number"] += 1
        return "[phone number hidden]"

    def email(m: re.Match) -> str:
        if m.group(0).lower() == user_email.lower():
            return m.group(0)  # the customer's own email stays
        counts["email address"] += 1
        return "[email hidden]"

    masked = CARD.sub(card, text)      # cards first, so a card is never read as a phone number
    masked = PHONE.sub(phone, masked)
    masked = EMAIL.sub(email, masked)
    changes = [f"{n} {kind}{'s' if n > 1 else ''}" for kind, n in counts.items() if n]
    return {"masked_text": masked, "count": sum(counts.values()), "changes": changes}


def _mask_in_code(callback_context: CallbackContext) -> types.Content:
    """All the work happens here, in code; the model is never called."""
    content = callback_context.user_content
    raw = "".join(p.text or "" for p in content.parts) if content and content.parts else ""
    request = json.loads(raw)
    result = mask(request["text"], request["user_email"])
    return types.Content(role="model", parts=[types.Part(text=json.dumps(result))])


masker_agent = LlmAgent(
    name="data_masker",
    model="gemini-2.5-flash",  # required by ADK; never called, the callback answers first
    description="Data Masker: hides other people's emails, phone numbers and card numbers in a reply.",
    before_agent_callback=_mask_in_code,
)

app = to_a2a(masker_agent, host="127.0.0.1", port=10003)
