"""L0 vault — the append-only Markdown journal that is Eva's source of truth.

Every turn the user writes lands here first, as plain Markdown on disk: one file
per day (``local_vault/journal/YYYY-MM-DD.md``), YAML frontmatter at the top, and
each turn appended below with a timestamp. This is the stable storage contract —
readable with any text editor, ``grep``, or a backup script, and it never depends
on a database to be understood. If every derived store (SQLite, ChromaDB) is
deleted, this directory still holds the user's whole journal in full.

The module is deliberately tiny and does exactly one thing: append text durably.
Extraction, indexing, and analysis all read *from* here; nothing here reads from
them.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from llm import config

# Serializes day-file writes so two concurrent turns can't both create the
# frontmatter or interleave their appended blocks. A plain ``threading.Lock``
# (not ``asyncio.Lock``) because callers run the write on a worker thread via
# ``asyncio.to_thread``. Capture is rare and the critical section is tiny, so the
# contention cost is nil — cheap insurance for the L0 source-of-truth format.
_WRITE_LOCK = threading.Lock()


def journal_dir() -> Path:
    """Return the directory holding the daily journal Markdown files.

    Lives inside the user-owned vault (``local_vault/journal``) so the whole
    journal is one portable folder. Exists so every writer/reader agrees on one
    location rather than hardcoding the path.
    """
    return config.vault_dir() / "journal"


def day_path(date: str) -> Path:
    """Return the Markdown file path for a given ``YYYY-MM-DD`` date.

    One file per day is the unit of the vault: it keeps each day human-scannable
    and makes date-range recall (Phase later) a simple directory listing. Exists
    so the day→file mapping is defined in exactly one place.
    """
    return journal_dir() / f"{date}.md"


def append_entry(
    text: str,
    *,
    entry_type: str = "chat",
    when: datetime | None = None,
) -> dict:
    """Append one entry to today's day-file and return its metadata.

    ``text`` is the user's words verbatim; ``entry_type`` is ``"chat"`` (a turn
    in conversation) or ``"journal"`` (a written entry, Phase 3). The file is
    created with frontmatter on first write of the day, then every entry is
    appended as a timestamped Markdown block — never rewritten, never reordered
    (append-only is what makes L0 trustworthy as the source of truth).

    ``text`` is written verbatim — L0 is the user's unedited words and must match
    what the derived SQLite store keeps; trimming here would silently diverge the
    two. (Empty/whitespace-only turns are rejected upstream before they reach
    capture.)

    Returns ``{"date", "time", "timestamp", "type", "path"}`` so the caller can
    mirror the same identity into the derived SQLite store with a single shared
    timestamp. Exists because durable capture must happen before — and
    independent of — anything the model does; saving never waits on the LLM.
    """
    moment = when or datetime.now()
    date = moment.strftime("%Y-%m-%d")
    time = moment.strftime("%H:%M:%S")

    path = day_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Hold the lock across the existence check and both writes: the "is this a new
    # day?" test and the frontmatter/block writes must be one atomic unit, or two
    # concurrent turns could double-write the header or interleave blocks.
    # newline="\n" keeps the file plain LF on Windows too, so the Markdown reads
    # identically everywhere and diffs/backups stay clean.
    with _WRITE_LOCK:
        is_new_day = not path.exists()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            if is_new_day:
                handle.write(f"---\ndate: {date}\n---\n\n# Journal — {date}\n")
            handle.write(f"\n## {time} · {entry_type}\n\n{text}\n")

    return {
        "date": date,
        "time": time,
        "timestamp": moment.isoformat(timespec="seconds"),
        "type": entry_type,
        "path": str(path),
    }
