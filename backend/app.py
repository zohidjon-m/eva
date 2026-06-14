"""Eva backend — FastAPI application.

This is the spine of Eva's local backend (Process 2 in the architecture). For
Phase 0 it does exactly one thing: answer a health check so the desktop shell
can show whether the backend is alive. Everything else (model, vault, chat)
arrives in later phases.

Privacy is a hard rule for Eva: this server binds to localhost only (127.0.0.1,
port 8420) and makes no outbound network calls. See ``dev.ps1`` for how it is
launched in development.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Eva Backend", version="0.0.0")

# The frontend runs in the Tauri webview (origin ``tauri://localhost``) or, during
# browser-based development, in Vite on port 1420. We allow exactly those local
# origins so the status dot can reach ``/health`` — nothing wider, since Eva must
# never expose itself beyond this machine.
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


@app.get("/health")
def health() -> dict:
    """Report that the backend is up and whether the LLM model is present.

    The desktop shell polls this to drive its status dot. ``model_present`` is
    hardcoded ``False`` in Phase 0 because no model is wired yet; Phase 1 replaces
    this with a real check against the GGUF / llama-server. Exists so the UI has a
    single, stable truth source for "is Eva ready?".
    """
    return {"status": "ok", "model_present": False}
