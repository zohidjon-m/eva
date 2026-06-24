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

## Phase 1 — Model online: streaming chat (backend only) ✅

**Status:** complete · **Date:** 2026-06-14

Gemma 4 E2B streams tokens through the backend over a WebSocket, proven without
any UI. The missing-model/binary path degrades gracefully instead of crashing.

### What shipped
- **`backend/llm/` package** (the app's heart):
  - `config.py` — single source of truth: ports (llama-server `11500`), the model
    id (`unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL`), generation params
    (temp 1.0 / top-p 0.95 / top-k 64), and vault paths. `model_present()` = a
    `*.gguf` exists under `local_vault/models`; `llama_server_bin()` resolves via
    `EVA_LLAMA_SERVER_BIN` → vault runtime → `PATH`.
  - `server.py` — supervises one native `llama-server` child: `status()`,
    `ensure_running()` (idempotent, polls readiness, never raises), `stop()`.
    Launched localhost-only and loads the model from a concrete local file with
    `-m` — no `-hf`/network path is ever invoked, so runtime is offline by
    construction.
  - `client.py` — async `stream_chat(messages)` against the OpenAI-compatible
    endpoint; parses SSE, yields tokens; raises `LlamaUnavailable` on failure.
- **`backend/app.py`** — real `/health` (delegates to `server.status()`); new
  `WS /chat` (single-turn streaming with `token` / `done` / `error` frames);
  lifespan hook warms the model on boot and stops it on shutdown.
- **Scripts** — `scripts/download_model_win.ps1` (resolves the latest llama.cpp
  `bin-win-cpu-x64` release, extracts to `local_vault/runtime/`, fetches+verifies
  the GGUF into `local_vault/models/`; idempotent on the binary step),
  `download_model_mac.sh` (parity, untested on macOS), `ws_test.py` (sends a
  message, prints the streamed reply).
- **Dep:** added `httpx` (websockets already came via `uvicorn[standard]`).

### Key decisions
- **Native `llama-server`, not Docker.** Docker Desktop is a ~1 GB+ end-user
  dependency requiring virtualization — wrong for a consumer desktop app and
  *larger*, not smaller. Native matches the arch doc (§4) and is the Ollama /
  LM Studio / Jan model: small app, heavy bits fetched on first run, fastest
  readiness. CPU-only for now (GPU is a later optimization).
- **Model is downloaded directly, not via `-hf`.** llama.cpp's built-in HF
  downloader proved flaky on the multi-GB file (repeated "Failed to read
  connection", ~145 MB in 22 min) and also pulled the multimodal `mmproj`
  projector we don't need. The scripts now `curl` the one GGUF
  (`gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf`) directly with resume + retries into
  `local_vault/models/`, and the server loads it with `-m`.
- **`.ps1` files must be ASCII** — Windows PowerShell 5.1 reads UTF-8-no-BOM as
  CP1252, turning em-dashes into stray curly quotes that break parsing.
- **Privacy:** only the download scripts touch the network; runtime is
  `--offline` + localhost-bound, no telemetry.

### Verify
- `powershell scripts\download_model_win.ps1` → binary in `local_vault/runtime/`,
  `*.gguf` in `local_vault/models/`.
- Start backend → `curl http://127.0.0.1:8420/health` → `model_present:true,
  llama_running:true`.
- `python scripts\ws_test.py "hello"` → a coherent reply streams token-by-token.
- Rename the `.gguf` away → `/health` flips to `model_present:false` with the
  download command; `WS /chat` returns a clean `error` frame; no crash.

### Left for later phases
- `download_model_mac.sh` unverified (no Mac available).
- No persistence yet — every chat turn is ephemeral (Phase 2 adds the vault).
- Minimal neutral system prompt inline; the real `eva_system.md` persona is Phase 4.
- llama.cpp binary is fetched to the vault in dev; bundling it into the installer
  as a sidecar is Phase 15.

---

## Phase 2 — Vault: real entry capture (L0 + basic L1) ✅

**Status:** complete · **Date:** 2026-06-15

Every chat turn is now genuinely persisted from day one: written to plain
Markdown (the source of truth), mirrored into SQLite for querying, and enriched
by a background extraction — none of which can block or undo the save.

### What shipped
- **`backend/memory/vault.py` (L0)** — append-only daily journal. One file per
  day at `local_vault/journal/YYYY-MM-DD.md` with YAML frontmatter; each turn
  appended as a timestamped Markdown block (`## HH:MM:SS · <type>`). Plain LF
  UTF-8, readable in any editor or with `grep`; never rewritten or reordered.
- **`backend/memory/db.py`** — derived SQLite store at `local_vault/eva.db`:
  `entries` (id, date, type, text, created_at) and `extractions` (entry_id,
  summary, mood −5..+5, entities/themes as JSON, created_at), plus an FTS5 index
  over `entries.text` kept in sync by triggers (external-content pattern).
  Fresh connection per call (thread-safe across the request + background task);
  foreign keys on so deleting an entry cascades to its extraction.
- **`backend/memory/extract.py` (basic L1)** — one bounded, low-temperature
  model call per entry → strict JSON `{summary, mood, entities, themes}`, via a
  few-shot prompt. Defensive `parse_extraction` recovers JSON from prose/fences
  and normalizes/clamps fields; on parse failure it retries once, then stores
  nulls. Never raises into the caller.
- **`backend/llm/client.py`** — added `complete_chat` (non-streaming one-shot
  completion) for extraction, alongside the existing `stream_chat`.
- **`backend/app.py`** — `WS /chat` now captures the user's turn (vault + DB)
  and schedules background extraction *before* touching the model, so capture is
  independent of model readiness. `init_db()` runs at startup. Background tasks
  are tracked in a set so they aren't GC'd; all their failures are logged and
  swallowed.
- **Tests** — `backend/tests/test_extract.py` (8 cases) covers the parser:
  clean JSON, fenced/prose-wrapped recovery, mood clamping/coercion, missing
  fields → defaults, non-list tags → `[]`, and malformed → `None`.
  `backend/conftest.py` puts `backend/` on the path so `import memory` works.
- **Dep:** added `pytest` (dev) to `requirements.txt`.

### Key decisions
- **Capture before the model, always.** The save path (vault → DB) runs and is
  awaited before `ensure_running`; extraction is fire-and-forget afterward. A
  down or slow model can never cost the user a saved entry. This is the
  "capture must be real from day one" rule made structural.
- **Markdown is the source of truth; SQLite is a rebuildable mirror.** Per the
  memory architecture doc, L0 never depends on the DB. Verified: deleting
  `eva.db` leaves the journal complete and readable.
- **Extraction degrades to nulls, never blocks.** Model-unavailable or
  unparseable output stores `{summary:null, mood:null, entities:[], themes:[]}`
  rather than retrying forever or failing the turn.
- **Eva's reply is not yet persisted** — only the user's turns are captured (the
  journal is the user's words). Storing assistant turns, if wanted, is a later
  decision.

### Verify
- Send 3 chat messages → today's `local_vault/journal/<date>.md` contains all 3
  as timestamped blocks; `entries` has 3 rows and (after a moment) `extractions`
  has 3 rows with plausible mood/summary.
- Delete `local_vault/eva.db` → the Markdown is untouched and fully readable.
- `cd backend && python -m pytest` → 8 passed (parser handles malformed output).

### Left for later phases
- Extraction quality depends on the live model; with the model down it correctly
  stores nulls (re-extraction/backfill is a later concern).
- L2 (embeddings/ChromaDB) and richer L1 fields (events, goals, open loops) are
  later phases — Phase 2 keeps the schema deliberately tight.
- The journal UI and the `journal` entry type path land in Phase 3.

### Post-review hardening (same day)
Four review findings fixed, all tightening the Phase 2 contract:
- **L0 write failure is now a hard error.** A failed vault write sends an
  `error` frame and streams no reply — we never pretend to journal a turn we
  couldn't save. A DB write failure stays soft (Markdown is the truth): logged,
  reply proceeds, extraction skipped (no row to attach to).
- **Extraction owns its own model-readiness.** The background task waits for
  `ensure_running()` before calling the model, so it can't race a cold start and
  store premature nulls; if the model never comes up it records a null row rather
  than leaving the entry with none — every saved entry ends up with exactly one
  extraction (possibly null). Capture still happens before the model (durability
  unchanged).
- **Vault writes are serialized** by a module-level `threading.Lock` (writes run
  on worker threads via `asyncio.to_thread`), closing the day-file TOCTOU race
  that could double-write frontmatter or interleave blocks.
- **L0 stores the user's text verbatim** (dropped `text.strip()`), so the vault
  and SQLite never diverge — confirmed: with leading/trailing spaces the `.md`
  block byte-matches `entries.text`.

---

## Phase 5 — App shell UI + design system ✅

**Status:** complete · **Date:** 2026-06-24

> **Build-order note.** This was built against the v1 plan, where the app shell
> was Phase 3. Plan v2 (2026-06-24) inserted two capture-substrate phases ahead
> of the UI — **Phase 3 (L1 full episode schema)** and **Phase 4 (L2 semantic
> index)** — renumbering the shell to **Phase 5**. Those two phases are now
> defined and **not yet built**; the shell was completed ahead of them and they
> are the next work (before Phase 6, the chat surface).

The Phase-0 status-dot placeholder is replaced with the full frame of a product:
a persistent sidebar, a top bar, a real design-token system, reusable
primitives, and intentional empty states for all six sections. No feature logic —
just the shell, built so the app already *looks* finished.

### What shipped
- **Design tokens** (`ui/src/styles/tokens.css` + `global.css`) — a "warm paper /
  journal" palette (soft off-white, warm neutrals, terracotta ink accent) with a
  full dark variant, a type scale, spacing/radii/shadow scales, and base styles.
  Theme is driven by a `data-theme` attribute on `<html>` (no media-query branch —
  one code path).
- **Self-hosted fonts** (`ui/public/fonts/`) — Fraunces (display) + Inter (UI),
  latin variable woff2 loaded via `@font-face`. No CDN at runtime, so the offline
  guarantee holds; the family stacks fall back to system fonts if a file is missing.
- **Theme + health hooks** (`ui/src/lib/`) — `useTheme` (system default + manual
  toggle, persisted to `localStorage`) and `useBackendHealth` (the Phase-0 `/health`
  poll, lifted out of `App.tsx` into a hook so the top bar can surface it).
- **Primitives** (`ui/src/components/`, each `.tsx` + `.module.css`) — `Button`
  (primary/ghost/subtle), `Input`/`Textarea`, `Card`, `EmptyState`, plus an inline
  SVG `icons.tsx` set (no icon font/package).
- **Layout** (`ui/src/components/layout/`) — `AppLayout` (CSS-grid shell owning the
  active view + theme), `Sidebar` (wordmark + six nav items, active highlight),
  `TopBar` (section title, visual-only persona selector, "Offline ✓" badge, live
  status dot, theme toggle). Navigation is a local `View` union — **no router**.
- **Six section screens** (`ui/src/sections/`) — Chat · Journal · Library · Insights ·
  Profile · Settings, each a composed empty state with copy true to its real
  future purpose.
- **Rewire** — `App.tsx` is now a thin `<AppLayout/>` wrapper; `main.tsx` imports
  the global stylesheet; the old `App.css` is deleted.

### Key decisions
- **No new dependencies.** Plain React 19 + Vite + **CSS Modules** (built into
  Vite) for scoped styles; no router, UI library, or CSS framework — matching the
  repo's deliberately-tiny-deps ethos. Routing is local state because Eva is a
  single-window desktop app with a fixed sidebar.
- **Fonts are bundled, not fetched at runtime.** A CDN font would break the
  offline guarantee, so the woff2 files ship in the repo (`ui/public/fonts/`).
- **Aesthetic: warm paper / journal** (chosen with the user) — intimate and
  analog, like a private notebook.
- **The persona selector is visual-only** — `POST /persona` is wired with the
  chat work in Phase 4.

### Verify
- `cd ui && npm run dev` (or `.\dev.ps1`) → app loads into the new layout, no
  console errors.
- Click through all six sections → each renders an intentional empty state; the
  active nav item highlights and the top-bar title updates.
- Toggle dark/light → palette flips cleanly and the choice persists across reload.
- Stop the backend → the top-bar status dot turns red within ~3 s (health poll
  intact), no crash; "Offline ✓" stays.
- `cd ui && npm run build` → `tsc` + Vite build pass (47 modules).

### Left for later phases
- Persona selector and the status dot are presentational/observational only; the
  real chat surface lands in Phase 6, real persona switching in Phase 9, and the
  feature screens across Phases 6–19.
- No responsive collapse of the sidebar yet (the fixed window size makes it
  unnecessary for now; the top-bar health label hides under 860px).

---
