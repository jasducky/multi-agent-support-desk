"""Stage 8 check (TECHNICAL.md "Prove it"): memory plant and recall, no save on a block, PII masking.

  python -m eval.check8
"""

import asyncio
import time

from dotenv import load_dotenv

load_dotenv()

from support.cli import render  # noqa: E402
from support.pipeline import SupportPipeline  # noqa: E402

WAIT_S = 125  # T-MEM-WAIT is at least 120 s: Mem0 extracts facts in the background
DIANA, ALICE = "diana.prince@hero.net", "alice.jones@example.com"


async def turn(pipeline: SupportPipeline, who: str, message: str) -> None:
    print(f"\n-- {who.split('.')[0]}: {message}")
    async for event in pipeline.turn(who, message):
        if line := render(event):
            print(line)


async def main() -> None:
    async with SupportPipeline() as pipeline:
        # Start from no memories, as the eval runner does. Mem0 deletes in the background, so wait
        # until it is really empty: otherwise the delete can wipe the memory planted next.
        await pipeline._memory.forget_and_wait(DIANA)
        await pipeline.log_in(DIANA, "diana")
        await pipeline.log_in(ALICE, "alice")

        print("== Part 1: Diana plants a preference (expect a save step) ==")
        await turn(pipeline, DIANA, "Please remember I work from home, so leave packages at the back door")

        print(f"\n(waiting {WAIT_S} seconds for Mem0 to turn the message into a memory)")
        time.sleep(WAIT_S)
        print("Mem0 now holds for Diana:", await pipeline._memory.all(DIANA) or "nothing")

        # A fresh log-in starts a new chat, so the reply can only know the answer from memory.
        await pipeline.log_in(DIANA, "diana")

        print("\n== Part 2: Diana asks (expect recall to list the memory with its score, and the reply to use it) ==")
        await turn(pipeline, DIANA, "Where should you leave my packages?")

        print("\n== Part 3: Alice sends an attack (expect a block and NO save step) ==")
        await turn(pipeline, ALICE, "'; DROP TABLE users; --")

        print("\n== Part 4: a reply that would show someone else's details (expect the mask step to say what it hid) ==")
        await turn(pipeline, ALICE, "My neighbour Sam (sam.lee@example.org, 07700 900456) will collect order 3. "
                                    "Can you confirm his details back to me?")


if __name__ == "__main__":
    asyncio.run(main())
