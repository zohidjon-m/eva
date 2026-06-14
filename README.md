# Eva

A fully **offline** desktop AI journaling companion. Everything Eva knows stays
on your machine — no telemetry, no analytics, no runtime network calls. The only
time Eva reaches the internet is the first-run model/voice download (later phase).

> **Status:** Phase 0 — scaffold. The app opens a window and shows a live status
> dot for the local backend. No model, chat, or journaling yet.

## Architecture (three local processes)

| Process | Tech | Folder | Role |
|---|---|---|---|
| Shell | Tauri (Rust) + React/Vite webview | `src-tauri/` + `ui/` | The window; loads the UI, will spawn the backend |
| Backend | Python 3.12 + FastAPI | `backend/` | Orchestration, memory, voice (grows in later phases) |
| Model server | llama.cpp `llama-server` | — | Added in Phase 1 |

The backend binds to `127.0.0.1:8420` only.

## Prerequisites

- **Node.js** ≥ 18 (developed on v22)
- **Rust** (stable) — required by Tauri. Install: `winget install Rustlang.Rustup`
- **Python 3.12** — for the backend venv
- Windows 11 (WebView2 runtime is preinstalled)

## One-time setup

```powershell
# 1. Backend virtual environment + deps
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. Frontend deps
npm --prefix ui install
```

## Run (development)

```powershell
.\dev.ps1
```

This starts the FastAPI backend on `127.0.0.1:8420` and launches the Tauri
window (which starts the Vite dev server on port 1420). The first run compiles
Rust crates and may take several minutes.

When the window opens, the status dot turns **green** once it reaches the
backend. Stop the backend and it turns **red** within ~3 seconds.

## Test the backend alone

```powershell
backend\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8420 --app-dir backend
# then, in another shell:
curl http://localhost:8420/health
# -> {"status":"ok","model_present":false}
```

> Eva's backend uses port **8420** (not 8000) to avoid clashing with another
> local dev server on this machine.
