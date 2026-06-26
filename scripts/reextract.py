"""Rebuild the derived database (L1) from the L0 Markdown vault.

This is Eva's proof that the database is *derived, not truth*: it re-creates every
entry and its full L1 episode record by reading the journal Markdown back and
running extraction over it. Run it after the L1 schema grows (it backfills new
fields onto entries captured under an older schema), or any time the database is
lost or suspect.

**L0 is read-only here.** The script only ever *reads* the journal files and
writes the rebuildable database — it never modifies a single byte of the user's
words. Two properties make a rebuild safe (Phase 3.5 / ADR-001):

- **Identity is preserved.** Each entry is matched to its row by the stable ``uid``
  carried in L0 (``upsert_entry``), so a rebuild *reuses* the existing row instead
  of minting a new id — every evidence pointer that cites an entry stays valid.
- **The rebuild is hash-gated.** An entry whose L0 text is unchanged since its last
  model-backed extraction (same ``source_hash``) is skipped — no model call — so a
  second run is fast and only genuinely-changed (or never-extracted) entries are
  re-run. This is the same mechanism a single-entry edit recompute (Phase 7.5) uses.

If the on-disk schema predates Phase 3.5 (no ``uid`` column), the script rebuilds
the database fresh once to migrate it, then proceeds. Legacy entries that have no
``uid`` in L0 are refused — run ``scripts/migrate_uids.py`` first to stamp them.

Extraction needs the local model: with llama-server up, each entry yields its full
record; with the model down, every changed entry stores null (the same contract as
live capture) and is left ungated so a later run re-extracts it — so a *complete*
rebuild requires the model running.

Usage (from the repo root, with the model available):
    python scripts/reextract.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Scripts have no conftest to put the backend package on the path, so do it here:
# backend/ is a sibling of this scripts/ dir under the repo root.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND))

from llm import server  # noqa: E402  (import after sys.path setup)
from memory import db, extract, vault  # noqa: E402

# The sub-tables whose row counts are worth reporting after a rebuild, so a human
# can eyeball that structure actually landed (and compare against a live run).
_REPORT_TABLES = (
    "entries",
    "extractions",
    "emotions",
    "entities",
    "goals",
    "behaviors",
    "decisions",
    "open_loops",
    "self_judgments",
)


async def rebuild() -> None:
    """Re-derive every entry + L1 record from L0, preserving uids, hash-gated.

    Ensures the schema is current (rebuilding the file once if it predates Phase
    3.5), ensures the model is up, then replays the vault: each entry is upserted
    by its ``uid`` and re-extracted only when its text changed since the last
    model-backed extraction. Prints per-table row counts plus how many entries were
    extracted vs. skipped. Exists as the single, scriptable rebuild path the storage
    contract promises — and as the migration tool when the schema changes.
    """
    db.init_db()
    if not db.schema_is_current():
        db.reset_db()
        print("schema upgraded: rebuilt eva.db with uid/source_hash columns")

    state = await server.ensure_running()
    if not state.get("ready"):
        print(
            "warning: model is not ready — extractions will be stored as nulls. "
            "Start llama-server for a complete rebuild.",
            file=sys.stderr,
        )

    extracted = skipped = 0
    for entry in vault.iter_entries():
        uid = entry["uid"]
        if uid is None:
            print(
                f"error: entry at {entry['timestamp']} has no uid in L0. "
                "Run `python scripts/migrate_uids.py` first to stamp legacy entries.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        entry_id = db.upsert_entry(
            uid=uid,
            date=entry["date"],
            entry_type=entry["type"],
            text=entry["text"],
            created_at=entry["timestamp"],
        )

        # Hash gate: skip an entry already extracted from this exact text. A null
        # extraction written while the model was down has source_hash None, so it
        # never matches and is re-extracted here once the model is up.
        new_hash = vault.content_hash(entry["text"])
        if db.source_hash_for(entry_id) == new_hash:
            skipped += 1
            print(f"  [skip] {entry['timestamp']} · {entry['type']} · {uid}")
            continue

        if state.get("ready"):
            record = await extract.extract(entry["text"])
            source_hash = new_hash
        else:
            record = extract.empty_extraction()
            source_hash = None  # leave ungated so a later run re-extracts it
        db.save_extraction(
            entry_id,
            record=record,
            created_at=datetime.now().isoformat(timespec="seconds"),
            source_hash=source_hash,
        )
        extracted += 1
        print(f"  [ext ] {entry['timestamp']} · {entry['type']} · {uid}")

    total = extracted + skipped
    print(
        f"\nrebuilt {total} entr{'y' if total == 1 else 'ies'} from L0 "
        f"({extracted} extracted, {skipped} unchanged):"
    )
    for table in _REPORT_TABLES:
        print(f"  {table:<16} {db.count_rows(table)}")


if __name__ == "__main__":
    try:
        asyncio.run(rebuild())
    finally:
        server.stop()
