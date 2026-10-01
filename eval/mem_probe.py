"""List (or clear) one customer's Mem0 memories. Scratch helper for checks.

  python -m eval.mem_probe diana.prince@hero.net            # list
  python -m eval.mem_probe diana.prince@hero.net --forget   # clear, then wait until empty
"""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from support.memory import Memory  # noqa: E402


async def main() -> None:
    email = sys.argv[1]
    memory = Memory()
    if "--forget" in sys.argv:
        print(f"cleared, empty after {await memory.forget_and_wait(email):.0f} seconds")
    for m in await memory.all(email):
        print("-", m)
    print(f"({len(await memory.all(email))} memories for {email})")


if __name__ == "__main__":
    asyncio.run(main())
