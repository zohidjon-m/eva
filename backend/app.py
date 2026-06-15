"""Eva backend — FastAPI application.

This is the spine of Eva's local backend (Process 2 in the architecture). As of
Phase 1 it does two things: report health (including real model readiness) and
stream chat tokens from the local Gemma model over a WebSocket. Vault capture,
the persona prompt, and the UI arrive in later phases.

Privacy is a hard rule for Eva: this server binds to localhost only (127.0.0.1,
port 8420) and makes no outbound network calls. It talks only to the local
llama-server it supervises. See ``dev.ps1`` for how it is launched in dev.
"""

import contextlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from llm import client, server


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the model on boot and stop it on shutdown.

    Warming llama-server at startup means the first chat turn is fast instead of
    paying model-load latency. Best-effort: if the binary or model is missing the
    backend still comes up healthy (just not "ready"), so the app never fails to
    launch over a missing model. Exists to own the llama-server lifecycle
    alongside the backend's own.
    """
    with contextlib.suppress(Exception):
        await server.ensure_running()
    try:
        yield
    finally:
        server.stop()


app = FastAPI(title="Eva Backend", version="0.1.0", lifespan=lifespan)

# The frontend runs in the Tauri webview (origin ``tauri://localhost``) or, during
# browser-based development, in Vite on port 1420. We allow exactly those local
# origins — nothing wider, since Eva must never expose itself beyond this machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Minimal, neutral system framing for Phase 1 so replies are coherent. The real
# Eva persona prompt (``eva_system.md``) is built in Phase 4 — deliberately not
# here.
_SYSTEM_PROMPT = (
    "You are Eva, a warm, concise companion. Reply naturally and briefly."
)


@app.get("/health")
def health() -> dict:
    """Report backend liveness and model readiness.

    The desktop shell polls this to drive its status dot and, when the model is
    missing, to show the download command. Delegates to the LLM supervisor so
    there is one truth source for "is Eva ready?".
    """
    return server.status()


@app.websocket("/chat")
async def chat(websocket: WebSocket) -> None:
    """Stream a single chat reply token-by-token over a WebSocket.

    Protocol (Phase 1, single-turn, no persistence): the client sends
    ``{"message": "..."}``; the server ensures llama-server is up, then emits
    ``{"type": "token", "text": ...}`` frames as Gemma generates, followed by a
    final ``{"type": "done"}``. If the model is unavailable or generation fails,
    it sends ``{"type": "error", "message", "hint"}`` instead of crashing the
    socket. Exists to prove the streaming spine end-to-end before any UI.
    """
    await websocket.accept()
    try:
        request = await websocket.receive_json()
        user_message = (request or {}).get("message", "")
        if not isinstance(user_message, str) or not user_message.strip():
            await websocket.send_json(
                {"type": "error", "message": "empty message", "hint": ""}
            )
            return

        state = await server.ensure_running()
        if not state.get("ready"):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": state.get("error", "model unavailable"),
                    "hint": state.get("hint", ""),
                }
            )
            return

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        try:
            async for token in client.stream_chat(messages):
                await websocket.send_json({"type": "token", "text": token})
            await websocket.send_json({"type": "done"})
        except client.LlamaUnavailable as exc:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": str(exc),
                    "hint": server.download_command(),
                }
            )
    except WebSocketDisconnect:
        # Client closed mid-turn; nothing to clean up for a single request.
        return
