# Eva — Implementation Progress

A running log of what's actually built, phase by phase. Source of truth for
"where are we." Each phase entry records what shipped, key decisions, and how to
verify it.

---

## Phase 0 — Scaffold: shell + backend + health ✅

**Status:** complete · **Date:** 2026-06-14

An empty but fully running app: a Tauri window talks to a local FastAPI backend
over localhost and shows a live status dot.

### What shipped
- **Backend** (`backend/`): FastAPI app with one route, `GET /health` →
  `{"status":"ok","model_present":false}`. Binds `127.0.0.1` only; CORS limited
  to the local dev origins. Deps: `fastapi`, `uvicorn[standard]` (venv at
  `backend/.venv`).
- **Frontend** (`ui/`): React + TypeScript + Vite. `App.tsx` renders an Eva
  landing view with a status dot that polls `/health` every 3 s
  (green = connected, red = unreachable).
- **Shell** (`src-tauri/`): Tauri 2 Rust shell at the repo root, loading the
  Vite frontend. No updater/telemetry.
- **Tooling**: `dev.ps1` launches backend + `tauri dev` together; `.gitignore`
  (venv, node_modules, target, `local_vault/`); `README.md` with setup/run/test.

### Key decisions
- **Backend port 8420**, not 8000 — port 8000 is occupied by an unrelated
  process on this machine. (Phase 1's llama-server uses 11500.)
- **Python 3.12** for the venv (3.11 not installed).
- **`src-tauri/` is a repo-root sibling** of `ui/` and `backend/`, mirroring the
  three-process architecture. The Tauri CLI is therefore invoked from the repo
  root (it only searches cwd + subfolders).
- Toolchain installed: Rust (MSVC) + Visual Studio 2022 Build Tools (for the
  `link.exe` linker).

### Verify
- `.\dev.ps1` → window opens, status dot turns **green**.
- `curl http://localhost:8420/health` → `200 {"status":"ok","model_present":false}`.
- Stop the backend → dot turns **red** within ~3 s, no crash; restart → green.
- First `tauri dev` build measured ~2m18s (compiles Rust once).

### Left for later phases
- `model_present` is hardcoded `false`; Phase 1 wires the real model check.
- Cargo crate is internally named `eva-app` (cosmetic; product name is "Eva").

---

## Phase 1 — Model online: streaming chat (backend only) ⏳

Not started.
