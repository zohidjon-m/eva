You are building "Eva", a fully offline desktop AI journaling companion.
Stack: Tauri (Rust shell) + React/Vite frontend + Python FastAPI backend +
llama.cpp llama-server running gemma-4-E2B-it-qat-GGUF (port 11500, thinking
mode OFF) + ChromaDB + SQLite + faster-whisper + Kokoro TTS + APScheduler +
FastEmbed. English only.

Rules:
1. Implement ONLY the phase given. Do not touch later phases. Do not refactor
   unrelated code.
2. Small, readable modules. Every public function gets a docstring saying what
   it does and why it exists. A human will read all of this code.
3. After implementing, run the phase's checks. Fix failures BEFORE reporting
   done. Then list: files changed, how to test manually, anything left TODO.
4. Privacy is hard law: no telemetry, no analytics, no outbound network calls
   at runtime. Only the first-run model/voice download is allowed.
5. Full journal entries are plain Markdown on disk — the source of truth.
   Databases are derived and rebuildable; Markdown never depends on them.
6. NOTHING IN THE PRODUCT IS HARDCODED OR SEEDED. Every value a user sees is
   computed from their real entries. Every layer (L0-L4) is rebuildable from L0.
   The only synthetic data permitted is a clearly-marked dev test fixture that
   flows through the REAL pipeline (real extraction, real L3 ops, real SQL) and
   is never shipped — mark such code  # DEV-FIXTURE  and gate it behind a flag.
7. Code counts; the model narrates. Never ask the model to count, rank, or
   connect across multiple entries. Heavy analysis is deterministic Python/SQL
   that hands the model a small, pre-counted, evidence-backed job.
8. Every L3 claim carries evidence pointers to the L1 entries that justify it.
   No pointer, no claim — code rejects an unsupported assertion.
9. If anything is ambiguous about data storage, privacy, or Eva's behavior:
   STOP and ask. Do not guess.
10. Before commiting, everything needs to be reviewed.
11. End every phase with a git commit: "phase-XX: <title>".
12. don't include the co-author when commiting.