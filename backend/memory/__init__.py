"""Eva's memory subsystem — the layered store behind the companion.

Phase 2 builds the bottom two layers:
- ``vault`` (L0): append-only daily Markdown, the source of truth on disk.
- ``db``: SQLite mirror (entries + extractions, FTS5) — derived, rebuildable.
- ``extract`` (basic L1): one bounded model call that turns an entry into a
  small structured record.

The governing rule (see ``docs/system/EVA_MEMORY_ARCHITECTURE.md``): L0 Markdown
never depends on the databases. Delete every ``.db`` and the user's words remain
complete and readable in plain text.
"""
