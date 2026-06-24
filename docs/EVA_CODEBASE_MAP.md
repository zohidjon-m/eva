# Eva — Codebase Map

**A file-by-file guide to the repository, for someone reading it for the first time.**

This document answers one question: *"What is every file here, and why does it
exist?"* Read it top-to-bottom once and you'll know where everything lives and
how the pieces fit. It is kept in sync with the code as the project grows — if
you add a file, add a line here.

For *why* Eva is built this way, see the design docs in
[`docs/system/`](system/); for *what gets built when*, see
[`docs/implementation/`](implementation/). This map is the "where things are"
companion to those.

---

## 1. What Eva is (the 30-second version)

Eva is a **fully offline desktop AI journaling companion**. You talk to it about
your day, by text (voice later), and it builds a private, evolving understanding
of you. Everything runs and stays on your machine. The only time it ever touches
the network is the one-time, first-run model download.

It runs as **three local processes**:

```
┌─────────────────────────────┐     HTTP/WS      ┌──────────────────────────┐    HTTP (OpenAI API)   ┌────────────────────────┐
│  1. Shell                   │  127.0.0.1:8420  │  2. Backend              │   127.0.0.1:11500      │  3. Model server       │
│  Tauri (Rust) + React UI    │ ───────────────► │  Python + FastAPI        │ ─────────────────────► │  llama.cpp             │
│  src-tauri/  +  ui/         │                  │  backend/                │                        │  llama-server (Gemma)  │
│  the window the user sees   │ ◄─────────────── │  brains: memory, model   │ ◄───────────────────── │  text generation       │
└─────────────────────────────┘   health, chat   └──────────────────────────┘    tokens, extraction  └────────────────────────┘
```

- **Shell** (`src-tauri/` + `ui/`) — the desktop window and the UI inside it.
- **Backend** (`backend/`) — the orchestrator: storage, memory, and the bridge
  to the model. This is where most of Eva's logic lives.
- **Model server** — a native `llama.cpp` process the backend supervises; it
  loads the Gemma model and generates text. Not a file in the repo — it's a
  binary downloaded into the (gitignored) vault on first run.

**Build status:** Phases 0–2 are complete (scaffold → streaming chat → real
entry capture), plus **Phase 5** (app shell + design system), which was built
ahead of Phases 3–4 (L1 full episode schema, L2 semantic index — defined in the
plan, not yet built). See [`EVA_PROGRESS.md`](implementation/EVA_PROGRESS.md) for
the running log.

---

## 2. Directory tree at a glance

```
eva/
├── README.md                 ← setup + run instructions (start here to run it)
├── dev.ps1                   ← one command to launch backend + shell in dev
├── notes.txt                 ← informal brainstorm scratchpad (not authoritative)
├── .gitignore
│
├── backend/                  ← Process 2: the Python brains
│   ├── app.py                ← FastAPI app: /health + WS /chat (the spine)
│   ├── conftest.py           ← makes `import memory` work under pytest
│   ├── requirements.txt      ← Python deps (deliberately tiny)
│   ├── llm/                  ← talking to the local model
│   │   ├── config.py         ← single source of truth: ports, model, paths
│   │   ├── server.py         ← supervises the llama-server child process
│   │   └── client.py         ← streams / completes chat from llama-server
│   ├── memory/               ← storing what the user writes
│   │   ├── vault.py          ← L0: append-only Markdown (the source of truth)
│   │   ├── db.py             ← derived SQLite mirror + full-text search
│   │   └── extract.py        ← L1: one model call → {summary,mood,...} JSON
│   ├── prompts/
│   │   └── eva_system.md     ← Eva's persona system prompt (wired in Phase 4)
│   └── tests/
│       └── test_extract.py   ← unit tests for the extraction JSON parser
│
├── scripts/                  ← one-off / dev utilities
│   ├── download_model_win.ps1← first-run download (Windows) — ONLY net access
│   ├── download_model_mac.sh ← same, for macOS (untested)
│   └── ws_test.py            ← manual proof that chat streaming works
│
├── ui/                       ← Process 1 (frontend half): React + Vite
│   ├── index.html            ← Vite entry HTML
│   ├── public/fonts/         ← self-hosted woff2 (Fraunces + Inter) — offline
│   ├── src/
│   │   ├── main.tsx          ← React bootstrap (mounts <App/>, imports global css)
│   │   ├── App.tsx           ← thin wrapper that mounts <AppLayout/>
│   │   ├── styles/           ← design tokens + global base styles
│   │   ├── lib/              ← useTheme + useBackendHealth hooks
│   │   ├── components/       ← primitives (Button/Input/Card/EmptyState/icons)
│   │   │   └── layout/       ← AppLayout, Sidebar, TopBar, nav config
│   │   ├── sections/         ← the six section screens (empty states)
│   │   └── vite-env.d.ts     ← Vite type shims
│   ├── package.json          ← frontend deps + scripts (React 19, Vite)
│   ├── vite.config.ts        ← Vite config (fixed port 1420 for Tauri)
│   └── tsconfig*.json         ← TypeScript config
│
├── src-tauri/                ← Process 1 (shell half): the Rust desktop wrapper
│   ├── src/main.rs           ← binary entrypoint
│   ├── src/lib.rs            ← Tauri app setup (sample `greet` command — scaffold)
│   ├── tauri.conf.json       ← window size, app id, dev/build commands
│   ├── Cargo.toml            ← Rust crate + Tauri dependencies
│   ├── build.rs              ← Tauri build script
│   ├── capabilities/default.json ← which Tauri APIs the window may use
│   └── icons/                ← app icons for all platforms
│
├── docs/                     ← all design + reference docs
│   ├── EVA_CODEBASE_MAP.md   ← THIS FILE
│   ├── system/               ← the "why": architecture
│   │   ├── EVA_SYSTEM_DESIGN.md
│   │   └── EVA_MEMORY_ARCHITECTURE.md
│   └── implementation/       ← the "when": build plan + progress
│       ├── IMPLEMENTATION_PLAN_V2.md
│       └── EVA_PROGRESS.md
│
└── local_vault/              ← user data + downloaded model (GITIGNORED, not in repo)
    ├── journal/YYYY-MM-DD.md ← the journal (L0 source of truth)
    ├── eva.db                ← derived SQLite store
    ├── models/               ← the downloaded Gemma GGUF
    └── runtime/llama.cpp/    ← the downloaded llama-server binary
```

---

## 3. The backend, file by file (`backend/`)

This is the heart of the app. If you read only one folder, read this one.

| File | What it does | Why it exists |
|---|---|---|
| [`app.py`](../backend/app.py) | The FastAPI application. Exposes `GET /health` (is Eva ready?) and `WS /chat` (a streaming chat turn). On a chat turn it: saves the user's words to the vault, mirrors them into SQLite, schedules background extraction, then streams the model's reply token-by-token. Binds `127.0.0.1:8420` only. | The spine that wires storage + model + UI together. Every request flows through here. |
| [`conftest.py`](../backend/conftest.py) | Empty pytest config file. Its presence makes `backend/` the test rootdir so tests can `import memory` / `import llm` exactly as the app does. | So `python -m pytest` "just works" without path juggling. |
| [`requirements.txt`](../backend/requirements.txt) | Python dependencies: `fastapi`, `uvicorn[standard]`, `httpx`, `pytest`. Kept intentionally small. | One place to install from; later phases add their own deps (ChromaDB, whisper, …). |

### `backend/llm/` — talking to the model

| File | What it does | Why it exists |
|---|---|---|
| [`config.py`](../backend/llm/config.py) | Single source of truth for the LLM subsystem: the llama-server host/port (`127.0.0.1:11500`), the model id + filename, generation parameters (temp 1.0, top-p 0.95, top-k 64), and every on-disk path (`vault_dir()`, `models_dir()`, `runtime_dir()`, `model_path()`). | So changing a port or path is a one-line edit, not a hunt. Everything else reads from here. |
| [`server.py`](../backend/llm/server.py) | Supervises the single native `llama-server` child process: `status()` (what's installed/running), `ensure_running()` (start it if needed, wait until ready, never raise), `stop()`. Launches it localhost-bound, loading the model from a local file (`-m`) — no network path is ever invoked. | Owns the model process's lifecycle and turns "model missing/starting" into graceful state instead of a crash. |
| [`client.py`](../backend/llm/client.py) | The HTTP client to llama-server's OpenAI-compatible API. `stream_chat()` yields the reply token-by-token (for chat); `complete_chat()` returns the whole reply at once (for extraction). Raises `LlamaUnavailable` on any failure. | The one place chat traffic leaves the backend; isolates SSE parsing and error handling. |

### `backend/memory/` — storing what the user writes

This implements the bottom two layers of the five-layer memory design (see
[`EVA_MEMORY_ARCHITECTURE.md`](system/EVA_MEMORY_ARCHITECTURE.md)). The golden
rule: **the Markdown is the truth; the database is a rebuildable mirror.**

| File | What it does | Why it exists |
|---|---|---|
| [`vault.py`](../backend/memory/vault.py) | **L0 — the source of truth.** `append_entry()` writes each user turn to `local_vault/journal/YYYY-MM-DD.md` (one file per day, YAML frontmatter, timestamped blocks), verbatim and append-only. Plain UTF-8 readable in any editor; a `threading.Lock` serializes writes so concurrent turns can't corrupt the file. | If every database is deleted, the user's whole journal still exists in plain text. This is the stable storage contract. |
| [`db.py`](../backend/memory/db.py) | The derived SQLite store at `local_vault/eva.db`: `entries` (every turn) and `extractions` (the per-entry structured record), plus an FTS5 full-text index kept in sync by triggers. Fresh connection per call (thread-safe). | Makes the vault queryable (search now; mood charts and recall later) without ever being the source of truth — delete it and it can be rebuilt from the Markdown. |
| [`extract.py`](../backend/memory/extract.py) | **L1 — basic extraction.** `extract()` makes one bounded, low-temperature model call per entry → strict JSON `{summary, mood, entities, themes}`. `parse_extraction()` defensively recovers JSON from messy model output and normalizes/clamps the fields; on failure it retries once, then stores nulls. | The only place the model touches a raw entry — kept to the smallest reliable job, because a small model is a good clerk but a bad historian. |

### `backend/prompts/`

| File | What it does | Why it exists |
|---|---|---|
| [`eva_system.md`](../backend/prompts/eva_system.md) | Eva's full persona system prompt — who she is, how she speaks, the "listen first" rule, the no-fabrication rule. | The character and behavioral contract for the companion. Currently the backend uses a minimal inline prompt; this file is wired in during Phase 4. |

### `backend/tests/`

| File | What it does | Why it exists |
|---|---|---|
| [`test_extract.py`](../backend/tests/test_extract.py) | 8 unit tests for `parse_extraction`: clean JSON, fenced/prose-wrapped recovery, mood clamping/coercion, missing fields → defaults, malformed → `None`. | The parser is the fragile seam between a messy model and the strict store, so it gets the most direct testing. Run with `cd backend && python -m pytest`. |

---

## 4. Scripts (`scripts/`)

| File | What it does | Why it exists |
|---|---|---|
| [`download_model_win.ps1`](../scripts/download_model_win.ps1) | First-run setup on Windows: fetches the prebuilt llama.cpp CPU binary and the Gemma GGUF model into `local_vault/`, then verifies the model loads. Idempotent and resumable. | **The only part of Eva permitted to touch the network.** After it runs once, Eva is fully offline. |
| [`download_model_mac.sh`](../scripts/download_model_mac.sh) | The macOS equivalent (parity with the Windows script; untested — no Mac available). | Cross-platform first-run setup. |
| [`ws_test.py`](../scripts/ws_test.py) | A tiny WebSocket client: connects to `WS /chat`, sends one message, prints the streamed reply. | The human-runnable proof that chat streaming works end-to-end, without needing the UI. |

---

## 5. The shell — frontend (`ui/`)

The React app shown inside the Tauri window. In dev, Vite serves it on port 1420.

Styling is plain **CSS Modules** (built into Vite — no router, UI library, or CSS
framework). All color/type/spacing comes from the design tokens; nothing
hard-codes a value. Navigation is local React state (a `View` union), not a router.

| File | What it does | Why it exists |
|---|---|---|
| [`src/main.tsx`](../ui/src/main.tsx) | React bootstrap: mounts `<App/>` and imports the global stylesheet. | Standard React/Vite entrypoint. |
| [`src/App.tsx`](../ui/src/App.tsx) | A thin wrapper that renders `<AppLayout/>`. | All screens live inside the layout shell. |
| [`src/styles/tokens.css`](../ui/src/styles/tokens.css) | The design system as CSS variables: the "warm paper" palette (light) + a `[data-theme="dark"]` override, type/spacing/radii/shadow scales, and `@font-face` for the bundled fonts. | One source of truth for the look; change a token, not a hunt. |
| [`src/styles/global.css`](../ui/src/styles/global.css) | Base/reset styles (box-sizing, body defaults from tokens, focus ring, scrollbars). Imports `tokens.css`. | The single global stylesheet; everything else is component-scoped. |
| [`src/lib/useTheme.ts`](../ui/src/lib/useTheme.ts) | Hook: resolves system preference, lets the user toggle light/dark, writes `data-theme` on `<html>`, persists the choice to `localStorage`. | Owns the theme with no dependency. |
| [`src/lib/useBackendHealth.ts`](../ui/src/lib/useBackendHealth.ts) | Hook: polls `/health` every 3 s → `{health, modelPresent}`. (The Phase-0 logic, lifted out of `App.tsx`.) | Lets the top bar surface the live shell ↔ backend bridge. |
| [`src/components/`](../ui/src/components/) | Reusable primitives, each `.tsx` + `.module.css`: `Button`, `Input`/`Textarea`, `Card`, `EmptyState`; plus `icons.tsx` (inline SVGs). | The shared UI vocabulary every screen is built from. |
| [`src/components/layout/`](../ui/src/components/layout/) | The app frame: `AppLayout` (grid shell, owns active view + theme), `Sidebar` (six nav items), `TopBar` (title, persona selector, "Offline ✓", status dot, theme toggle), and `nav.tsx` (the `View` union + nav config that drives all three). | The persistent chrome around every section. |
| [`src/sections/`](../ui/src/sections/) | The six section screens (Chat · Journal · Library · Insights · Profile · Settings), each an intentional empty state. | The destinations; feature logic fills them in later phases. |
| [`public/fonts/`](../ui/public/fonts/) | Self-hosted Fraunces + Inter variable woff2 (latin). | Bundled so no font is fetched at runtime — preserves the offline guarantee. |
| [`src/vite-env.d.ts`](../ui/src/vite-env.d.ts) | TypeScript type shims for Vite. | Editor/compiler support. |
| [`index.html`](../ui/index.html) | The HTML Vite serves; hosts the React root. | Vite's entry document. |
| [`package.json`](../ui/package.json) | Frontend dependencies (React 19, Vite, Tauri API/CLI) and scripts (`dev`, `build`, `tauri`). | Defines the frontend toolchain. |
| [`vite.config.ts`](../ui/vite.config.ts) | Vite config tuned for Tauri: fixed port 1420, don't watch `src-tauri/`, don't clear the screen (so Rust errors stay visible). | Tauri expects the dev server on a fixed port. |
| `tsconfig.json` / `tsconfig.node.json` | TypeScript compiler settings. | Type-checking the frontend. |
| `.vscode/extensions.json`, `src/assets/` | Editor hints and static assets (logos). | Scaffolding from the Vite/Tauri template. |

---

## 6. The shell — desktop wrapper (`src-tauri/`)

The Rust side of Tauri: it creates the native window and loads the UI. Note the
crate lives at the **repo root**, a sibling of `ui/` and `backend/` (not nested),
so the Tauri CLI must be run from the repo root.

| File | What it does | Why it exists |
|---|---|---|
| [`src/main.rs`](../src-tauri/src/main.rs) | The binary entrypoint; calls into the library's `run()`. Hides the console window on Windows release builds. | Standard Tauri 2 entrypoint. |
| [`src/lib.rs`](../src-tauri/src/lib.rs) | Sets up and runs the Tauri app. Currently registers a sample `greet` command from the template. | The app's Rust core. (The `greet` command is leftover scaffold; the real backend-spawn logic lands in a later phase.) |
| [`tauri.conf.json`](../src-tauri/tauri.conf.json) | App configuration: product name "Eva", identifier `com.eva.journal`, window size (980×720), and the dev/build commands + `frontendDist: ../ui/dist` that tie the Rust shell to the Vite frontend. | One config that connects the two halves of the shell. |
| [`Cargo.toml`](../src-tauri/Cargo.toml) | The Rust crate (`eva_app_lib`) and its Tauri dependencies. | Rust's manifest/dependency file. |
| [`build.rs`](../src-tauri/build.rs) | Runs `tauri_build::build()` at compile time. | Generates Tauri's compile-time glue. |
| [`capabilities/default.json`](../src-tauri/capabilities/default.json) | Declares which Tauri APIs the main window is allowed to use (`core:default`, `opener:default`). | Tauri's security model: capabilities are opt-in. |
| `icons/` | App icons for every platform (`.ico`, `.icns`, PNGs). | Bundled into the installer. |
| `Cargo.lock`, `.gitignore` | Locked dependency versions; ignores Rust build output. | Reproducible builds. |

---

## 7. Docs (`docs/`)

| File | What it covers |
|---|---|
| [`EVA_CODEBASE_MAP.md`](EVA_CODEBASE_MAP.md) | **This file** — what every file does. |
| [`system/EVA_SYSTEM_DESIGN.md`](system/EVA_SYSTEM_DESIGN.md) | The overall architecture: the three processes, components, data, runtime flows, goals and non-goals. The "why" at the system level. |
| [`system/EVA_MEMORY_ARCHITECTURE.md`](system/EVA_MEMORY_ARCHITECTURE.md) | The five-layer memory design (L0 vault → L4 analytics) and the rules that keep a small model honest ("code counts, the model narrates"). Essential reading before touching `backend/memory/`. |
| [`implementation/IMPLEMENTATION_PLAN_V2.md`](implementation/IMPLEMENTATION_PLAN_V2.md) | The phased build plan (v2 — everything real, nothing hardcoded): what each phase delivers and its acceptance tests. |
| [`implementation/EVA_PROGRESS.md`](implementation/EVA_PROGRESS.md) | A running log of what's actually been built, phase by phase, with key decisions and how to verify each. The source of truth for "where are we." |

---

## 8. Root files

| File | What it does |
|---|---|
| [`README.md`](../README.md) | Prerequisites, one-time setup, and how to run Eva. Start here to get it running. |
| [`dev.ps1`](../dev.ps1) | The dev launcher: starts the FastAPI backend (port 8420) and the Tauri shell (which starts Vite on 1420) together, and stops the backend when you close the window. |
| [`notes.txt`](../notes.txt) | An informal brainstorm scratchpad (mixed English/Uzbek) of future UI and memory ideas. **Not authoritative** — ideas, not specifications. |
| `.gitignore` | Excludes the venv, `node_modules`, Rust build output, and crucially `local_vault/` (the user's private data + the multi-GB model). |

---

## 9. Two flows that tie it together

**A chat turn (the main loop today):**
1. The UI opens a WebSocket to `WS /chat` on the backend and sends `{"message": "..."}`.
2. [`app.py`](../backend/app.py) saves the message to the vault
   ([`vault.py`](../backend/memory/vault.py)) — if that write fails, the turn is
   rejected, because an unsaved entry can't be recovered.
3. It mirrors the entry into SQLite ([`db.py`](../backend/memory/db.py)) and
   schedules background extraction ([`extract.py`](../backend/memory/extract.py)).
4. It ensures the model is up ([`server.py`](../backend/llm/server.py)) and
   streams the reply token-by-token ([`client.py`](../backend/llm/client.py))
   back over the socket.
5. In the background, the extraction task waits for the model, asks it for
   `{summary, mood, entities, themes}`, and writes that row to SQLite — so every
   saved entry ends up with exactly one extraction record.

**First run (the only time the network is touched):**
1. The user runs [`download_model_win.ps1`](../scripts/download_model_win.ps1).
2. It downloads the llama.cpp binary + the Gemma model into `local_vault/`.
3. From then on, [`server.py`](../backend/llm/server.py) loads the model from
   that local file. Eva never reaches the network again.

---

## 10. Where to start reading

- **Want to run it?** → [`README.md`](../README.md), then `dev.ps1`.
- **Want to understand the brains?** → [`backend/app.py`](../backend/app.py),
  then `backend/memory/` (vault → db → extract), then `backend/llm/`.
- **Want the big picture / the "why"?** →
  [`system/EVA_SYSTEM_DESIGN.md`](system/EVA_SYSTEM_DESIGN.md) and
  [`system/EVA_MEMORY_ARCHITECTURE.md`](system/EVA_MEMORY_ARCHITECTURE.md).
- **Want to know what's built and what's next?** →
  [`implementation/EVA_PROGRESS.md`](implementation/EVA_PROGRESS.md).

---

*This map describes the repository as of Phase 5 (app shell + design system),
built ahead of Phases 3–4. Keep it current: when you add, move, or remove a file,
update the matching row here.*
