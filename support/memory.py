"""Memory (Stage 8): recall before the agent, save after the Masker. Pipeline steps, not tools.

recall (R-1, R-2, R-3, R-5): search Mem0 with the customer's message, filtered to that customer,
asking for T-MEM-TOPK. A memory goes into the agent's input only if its score >= T-MEM-MINSCORE
and it is no longer than T-MEM-MAXCHARS; every candidate is reported with why.

save (R-4): only the customer's own message, only on turns that were not blocked. Card numbers
are removed first (Julia's decision: card numbers are never recorded).
"""

import os

os.environ.setdefault("MEM0_TELEMETRY", "False")  # Mem0's own usage analytics: off

from mem0 import AsyncMemoryClient  # noqa: E402

from support.telemetry import CARD  # noqa: E402

# From THRESHOLDS.md. Julia kept the cutoff at 0.25 (BUILD_LOG Stage 8).
TOPK = 5
MIN_SCORE = 0.25
MAX_CHARS = 500

HEADER = "Relevant memories about this customer (from Mem0):"


class Memory:
    def __init__(self):
        self._client = AsyncMemoryClient(api_key=os.environ["MEM0_API_KEY"])

    async def recall(self, email: str, message: str) -> list[dict]:
        """Every candidate, each with score, whether inserted, and why not."""
        found = await self._client.search(message, filters={"user_id": email}, top_k=TOPK)
        candidates = []
        for m in found.get("results", []):
            text, score = m.get("memory", ""), float(m.get("score") or 0)
            if score < MIN_SCORE:
                reason = f"below cutoff ({MIN_SCORE})"
            elif len(text) > MAX_CHARS:
                reason = f"too long ({len(text)} characters, limit {MAX_CHARS})"
            else:
                reason = None
            candidates.append({"memory": text, "score": round(score, 2), "inserted": reason is None,
                               "reason": reason, "saved": (m.get("created_at") or "")[:10]})
        return candidates

    @staticmethod
    def as_prompt(candidates: list[dict], message: str) -> str:
        """R-3: inserted memories go above the customer's message, under a fixed header."""
        kept = [c for c in candidates if c["inserted"]]
        if not kept:
            return message
        lines = "\n".join(f"- {c['memory']} (saved {c['saved']})" for c in kept)
        return f"{HEADER}\n{lines}\n\nCustomer's message:\n{message}"

    async def save(self, email: str, message: str) -> str:
        """R-4: the customer's own message only. Mem0 extracts facts later (status PENDING)."""
        result = await self._client.add(CARD.sub("[card number removed]", message), user_id=email)
        return str(result.get("status") or result.get("message") or "saved")

    async def forget(self, email: str) -> None:
        """Clear a customer's memories (the eval runner does this before a run)."""
        await self._client.delete_all(user_id=email)
