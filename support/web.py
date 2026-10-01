"""The web front end (Stage 9): the SPEC §7.2 routes and one HTML page, on port 8000.

Like the CLI, it only renders: POST /api/chat streams the exact events SupportPipeline.turn
yields, one JSON object per line (W-2, P-1). The page (support/static/index.html) reads that
stream as it arrives and draws each step (W-3, W-4).

Run: ./run.sh web   (or .venv/bin/uvicorn support.web:app --port 8000)
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

load_dotenv()

from guards import sanitizer  # noqa: E402
from support.agent import MODEL  # noqa: E402
from support.pipeline import SupportPipeline  # noqa: E402

PAGE = Path(__file__).parent / "static" / "index.html"
SERVICES = {"toolbox": "http://127.0.0.1:5001",
            "judge": "http://127.0.0.1:10002/.well-known/agent-card.json",
            "masker": "http://127.0.0.1:10003/.well-known/agent-card.json",
            "phoenix": "http://localhost:6006/healthz"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SupportPipeline() as pipeline:
        app.state.pipeline = pipeline
        yield


app = FastAPI(title="Customer support", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)  # no public API docs pages


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@app.post("/api/login")
async def login(request: Request):
    data = await body(request)
    user = await app.state.pipeline.log_in(str(data.get("email", "")), str(data.get("password", "")))
    if user is None:
        return error(401, "Invalid email or password.")
    return user


@app.post("/api/chat")
async def chat(request: Request):
    data = await body(request)
    user_id = str(data.get("user_id", "")).strip().lower()
    message = str(data.get("message", ""))
    if not message.strip():
        return error(400, "message is empty")
    if not app.state.pipeline.is_logged_in(user_id):
        return error(401, "Not logged in.")
    if len(message) > sanitizer.MAX_CHARS:
        return error(413, "message too long")

    async def lines():
        async for event in app.state.pipeline.turn(user_id, message):
            yield json.dumps(event) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/api/logout")
async def logout(request: Request):
    data = await body(request)
    app.state.pipeline.log_out(str(data.get("user_id", "")).strip().lower())
    return {"ok": True}


@app.get("/health")
async def health():
    status = {"status": "ok", "model": MODEL}
    status["db"] = await app.state.pipeline.db_ok()
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in SERVICES.items():
            try:
                (await client.get(url)).raise_for_status()
                status[name] = "ok"
            except httpx.HTTPError as e:
                status[name] = f"unreachable: {type(e).__name__}"
    status["mem0"] = await app.state.pipeline.mem0_ok()
    failing = [k for k, v in status.items() if k not in {"status", "model"} and v != "ok"]
    if failing:
        status["status"] = "failing: " + ", ".join(failing)
    order = ["status", "model", "db", "toolbox", "judge", "masker", "mem0", "phoenix"]
    return JSONResponse({k: status[k] for k in order}, status_code=503 if failing else 200)


@app.get("/")
async def page():
    return FileResponse(PAGE, media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("WEB_PORT", "8000")))
