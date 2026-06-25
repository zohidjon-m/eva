"""Eva backend — FastAPI application.

This is the spine of Eva's local backend (Process 2 in the architecture). As of
Phase 1 it does two things: report health (including real model readiness) and
stream chat tokens from the local Gemma model over a WebSocket. Vault capture,
the persona prompt, and the UI arrive in later phases.

Privacy is a hard rule for Eva: this server binds to localhost only (127.0.0.1,
port 8420) and makes no outbound network calls. It talks only to the local
llama-server it supervises. See ``dev.ps1`` for how it is launched in dev.
"""

import asyncio
import contextlib
import logging
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from llm import client, server
from memory import db, extract, vault

logger = logging.getLogger("eva.backend")

# Hold a strong reference to in-flight background extraction tasks. asyncio only
# keeps a weak reference to tasks, so without this set a fire-and-forget
# extraction could be garbage-collected mid-run. Tasks remove themselves on done.
_extraction_tasks: set[asyncio.Task] = set()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the model on boot and stop it on shutdown.

    Warming llama-server at startup means the first chat turn is fast instead of
    paying model-load latency. Best-effort: if the binary or model is missing the
    backend still comes up healthy (just not "ready"), so the app never fails to
    launch over a missing model. Also initializes the derived SQLite store so the
    very first captured turn has somewhere to land. Exists to own the
    llama-server lifecycle alongside the backend's own.
    """
    db.init_db()
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


async def _extract_turn(entry_id: int, text: str) -> None:
    """Run L1 extraction for a saved turn and store it; swallow all failures.

    Scheduled fire-and-forget after capture so the user never waits on it. It
    first waits for the model to be ready — this is what keeps it from racing a
    cold start and recording premature nulls. If the model is genuinely
    unavailable it stores an empty extraction rather than leaving the entry with no
    row at all, so every saved entry ends up with exactly one episode record
    (possibly null), matching the storage contract. It asks the model for the full
    L1 record (also storing the empty record if the output won't parse) and writes
    the result to SQLite. Any error here is logged and dropped — a failed
    extraction must never disturb the already-saved entry.
    """
    try:
        state = await server.ensure_running()
        if state.get("ready"):
            result = await extract.extract(text)
        else:
            result = extract.empty_extraction()  # model down → store nulls, not nothing
        await asyncio.to_thread(
            db.save_extraction,
            entry_id,
            record=result,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception:  # noqa: BLE001 — background task must never propagate
        logger.exception("extraction failed for entry %s", entry_id)


def _schedule_extraction(entry_id: int, text: str) -> None:
    """Launch background extraction for a turn, tracking the task safely.

    Keeps a strong reference in ``_extraction_tasks`` until the task finishes so
    it isn't garbage-collected, then auto-removes it. Exists so the chat handler
    can kick off extraction in one readable line without leaking tasks.
    """
    task = asyncio.create_task(_extract_turn(entry_id, text))
    _extraction_tasks.add(task)
    task.add_done_callback(_extraction_tasks.discard)


@app.websocket("/chat")
async def chat(websocket: WebSocket) -> None:
    """Stream a single chat reply token-by-token over a WebSocket.

    Protocol: the client sends ``{"message": "..."}``; the server first persists
    the user's turn to the vault (L0) — failing the turn hard if that write can't
    happen — then mirrors it into SQLite, schedules background extraction, ensures
    llama-server is up, and streams ``{"type": "token", "text": ...}`` frames as
    Gemma generates, followed by a final ``{"type": "done"}``. If the model is
    unavailable or generation fails, it sends ``{"type": "error", "message",
    "hint"}`` instead of crashing the socket — but the turn is already saved by
    then, so capture never depends on the model. The extraction task waits for the
    model itself (no cold-start race) and records a null row if it never comes up,
    so every saved entry gets exactly one extraction. Exists to prove the
    streaming spine end-to-end and to make every turn durable from day one.
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

        # Capture L0 first — the source of truth — before anything that can fail
        # on the model side. A vault write failure is a HARD error: we must not
        # stream a reply for a turn we couldn't actually save, because an unsaved
        # entry can never be recovered.
        try:
            record = await asyncio.to_thread(
                vault.append_entry, user_message, entry_type="chat"
            )
        except Exception:  # noqa: BLE001 — surface, don't crash the socket
            logger.exception("failed to write entry to vault (L0)")
            await websocket.send_json(
                {"type": "error", "message": "couldn't save your entry", "hint": ""}
            )
            return

        # Mirror into SQLite (derived, rebuildable). A DB failure is SOFT —
        # Markdown is the truth — so log and carry on without an entry id; we
        # simply can't attach an extraction to a row that doesn't exist.
        try:
            entry_id = await asyncio.to_thread(
                db.insert_entry,
                date=record["date"],
                entry_type="chat",
                text=user_message,
                created_at=record["timestamp"],
            )
        except Exception:  # noqa: BLE001 — DB loss must never deny a reply
            logger.exception("failed to mirror entry into SQLite")
            entry_id = None

        # Kick off extraction now that the entry is saved. The task waits for the
        # model itself before calling it, so this can't race a cold start, and it
        # records a null extraction if the model never comes up — every saved
        # entry gets exactly one row.
        if entry_id is not None:
            _schedule_extraction(entry_id, user_message)

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
