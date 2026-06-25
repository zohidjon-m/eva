"""Rebuild the derived database (L1) from the L0 Markdown vault.

This is Eva's proof that the database is *derived, not truth*: it deletes the
SQLite file and re-creates every entry and its full L1 episode record by reading
the journal Markdown back and running extraction over it again. Run it after the
L1 schema grows (it backfills the new fields onto entries captured under an older
schema), or any time the database is lost or suspect.

**L0 is read-only here.** The script only ever *reads* the journal files and
*replaces* the rebuildable database — it never modifies a single byte of the
user's words. Because it wipes and rebuilds from the same source, running it
twice yields the same database (idempotent); entry ids are reassigned but every
field and row count is reproduced.

Extraction needs the local model: with llama-server up, each entry yields its
full record; with the model down, every field stores null (the same contract as
live capture), so a *complete* rebuild requires the model running.

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
    """Delete the derived DB and re-derive every entry + L1 record from L0.

    Removes the SQLite file, recreates the schema, ensures the model is up, then
    replays the vault: for each entry in chronological order it re-inserts the row
    and re-runs extraction into the full L1 record. Prints a per-table row count at
    the end. Exists as the single, scriptable rebuild path the storage contract
    promises — and as the migration tool when the schema changes.
    """
    path = db.db_path()
    if path.exists():
        path.unlink()
        print(f"removed {path}")
    db.init_db()

    state = await server.ensure_running()
    if not state.get("ready"):
        print(
            "warning: model is not ready — extractions will be stored as nulls. "
            "Start llama-server for a complete rebuild.",
            file=sys.stderr,
        )

    count = 0
    for entry in vault.iter_entries():
        entry_id = db.insert_entry(
            date=entry["date"],
            entry_type=entry["type"],
            text=entry["text"],
            created_at=entry["timestamp"],
        )
        if state.get("ready"):
            record = await extract.extract(entry["text"])
        else:
            record = extract.empty_extraction()
        db.save_extraction(
            entry_id,
            record=record,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        count += 1
        print(f"  [{count}] {entry['timestamp']} · {entry['type']}")

    print(f"\nrebuilt {count} entr{'y' if count == 1 else 'ies'} from L0:")
    for table in _REPORT_TABLES:
        print(f"  {table:<16} {db.count_rows(table)}")


if __name__ == "__main__":
    try:
        asyncio.run(rebuild())
    finally:
        server.stop()
