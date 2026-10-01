"""Stage 3's throwaway chat loop: log in, then talk to the agent. Run with `./run.sh chat`.

Replaced in Stage 4 by the pipeline. Needs the Toolbox running (`./run.sh toolbox`).
"""

import asyncio
import getpass
import json

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from toolbox_core import ToolboxClient

from support.agent import build_agent

TOOLBOX_URL = "http://127.0.0.1:5001"
APP_NAME = "customer_support"


async def log_in(toolbox: ToolboxClient) -> tuple[str, str] | None:
    """Ask for email and password; the check-login tool answers with a name or nothing."""
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password: ")              # hidden input
    check_login = await toolbox.load_tool("check-login")  # from login_tools, never the agent's
    found = json.loads(await check_login(email=email, password=password) or "null")
    if isinstance(found, list):  # one row can come back as a row or as a list of one
        found = found[0] if found else None
    return (email, found["full_name"]) if found else None


async def main() -> None:
    load_dotenv()  # GOOGLE_API_KEY from .env
    async with ToolboxClient(TOOLBOX_URL) as toolbox:
        user = await log_in(toolbox)
        if user is None:
            print("Invalid email or password.")
            return
        email, name = user

        # M-5: the email is bound here, from the log-in. The model never sees these two
        # parameters, so it cannot choose or change them.
        tools = await toolbox.load_toolset(
            "support_agent_tools",
            bound_params={"customer_email": email, "user_email": email},
        )

        sessions = InMemorySessionService()
        runner = Runner(agent=build_agent(tools), app_name=APP_NAME, session_service=sessions)
        session = await sessions.create_session(app_name=APP_NAME, user_id=email)

        print(f"Hello {name}. Ask about your orders ('quit' to leave).")
        while True:
            text = input("You: ").strip()
            if text.lower() in {"quit", "exit", "q"}:
                break
            if not text:
                continue
            message = types.Content(role="user", parts=[types.Part(text=text)])
            async for event in runner.run_async(
                user_id=email, session_id=session.id, new_message=message
            ):
                for call in event.get_function_calls():  # show each tool the model chose
                    print(f"  [tool] {call.name}({call.args})")
                if event.is_final_response() and event.content and event.content.parts:
                    print("Agent:", "".join(p.text or "" for p in event.content.parts))


if __name__ == "__main__":
    asyncio.run(main())
