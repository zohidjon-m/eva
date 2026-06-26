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

import hashlib
import re
import secrets
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from llm import config

# Matches one entry's header line, e.g. ``## 14:03:27 · chat · a1b2c3d4``. The
# writer in ``append_entry`` produces exactly this shape, so parsing splits the
# day-file back into blocks on it. The ``uid`` group is optional so legacy
# day-files written before Phase 3.5 (``## 14:03:27 · chat``) still parse — they
# come back with ``uid=None`` and are stamped by ``scripts/migrate_uids.py``. A
# user line that merely starts with ``##`` won't match (it lacks the
# ``HH:MM:SS · type`` form), so prose is not mistaken for a header.
_BLOCK_HEADER = re.compile(r"^## (\d{2}:\d{2}:\d{2}) · (\S+)(?: · ([0-9a-f]+))?$")


def new_uid() -> str:
    """Mint a stable, content-independent entry id (8 hex chars).

    Written into the L0 block header at capture time and never derived from the
    text, so editing an entry never changes its ``uid`` — the property every upper
    layer's evidence pointer relies on (Phase 3.5 / ADR-001). 32 bits is ample for
    one person's journal; collisions are checked only at mint time. Zero
    dependencies (``secrets`` is stdlib) keeps the offline contract intact.
    """
    return secrets.token_hex(4)


def content_hash(text: str) -> str:
    """Return a stable short hash of an entry's L0 text.

    Stored beside an extraction as its ``source_hash`` so a rebuild can skip
    entries whose text is unchanged and a future edit can be detected as "this
    entry is dirty". Truncated SHA-256 — short enough to read, wide enough that an
    accidental collision between two real entries is not a practical concern.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

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

    Each block header carries a freshly minted ``uid`` (Phase 3.5) —
    ``## HH:MM:SS · type · uid`` — the stable identity every upper layer references
    and the handle a future edit (Phase 7.5) addresses; it is written here, at
    capture, so it lives in L0 itself and survives any rebuild.

    ``text`` is written verbatim — L0 is the user's unedited words and must match
    what the derived SQLite store keeps; trimming here would silently diverge the
    two. (Empty/whitespace-only turns are rejected upstream before they reach
    capture.)

    Returns ``{"date", "time", "timestamp", "type", "uid", "path"}`` so the caller
    can mirror the same identity into the derived SQLite store with a single shared
    timestamp and ``uid``. Exists because durable capture must happen before — and
    independent of — anything the model does; saving never waits on the LLM.
    """
    moment = when or datetime.now()
    date = moment.strftime("%Y-%m-%d")
    time = moment.strftime("%H:%M:%S")
    uid = new_uid()

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
            handle.write(f"\n## {time} · {entry_type} · {uid}\n\n{text}\n")

    return {
        "date": date,
        "time": time,
        "timestamp": moment.isoformat(timespec="seconds"),
        "type": entry_type,
        "uid": uid,
        "path": str(path),
    }


def parse_day_file(path: Path) -> list[dict]:
    """Parse one day-file back into its list of entry blocks, in file order.

    The inverse of :func:`append_entry`'s write: it splits the Markdown on the
    ``## HH:MM:SS · type · uid`` block headers and returns one
    ``{date, time, type, uid, text, timestamp}`` per block. ``uid`` is ``None`` for
    legacy blocks written before Phase 3.5 (no uid in the header) — those are
    stamped by ``scripts/migrate_uids.py``. Frontmatter and the ``# Journal —``
    title (everything before the first block header) are skipped. The structural
    blank lines the writer wraps each block in are stripped, while blank lines
    *inside* a multi-paragraph entry are preserved (an internal blank line is
    followed by more text, not by a header). Read-only — it never touches the file.
    Exists so derived layers (re-extraction, re-indexing, the journal UI) can read
    L0 back through one shared parser instead of re-implementing it.
    """
    date = path.stem
    lines = path.read_text(encoding="utf-8").split("\n")
    headers = [i for i, line in enumerate(lines) if _BLOCK_HEADER.match(line)]

    entries: list[dict] = []
    for index, start in enumerate(headers):
        match = _BLOCK_HEADER.match(lines[start])
        assert match is not None  # start came from a match above
        time, entry_type, uid = match.group(1), match.group(2), match.group(3)

        end = headers[index + 1] if index + 1 < len(headers) else len(lines)
        body = lines[start + 1 : end]
        while body and not body[0].strip():  # drop the blank line after the header
            body.pop(0)
        while body and not body[-1].strip():  # drop the trailing/separator blank line
            body.pop()

        entries.append(
            {
                "date": date,
                "time": time,
                "type": entry_type,
                "uid": uid,
                "text": "\n".join(body),
                "timestamp": f"{date}T{time}",
            }
        )
    return entries


def iter_entries() -> Iterator[dict]:
    """Yield every captured entry across all day-files, in chronological order.

    Walks ``local_vault/journal/*.md`` sorted by name (which, being
    ``YYYY-MM-DD``, sorts by date) and yields each block from
    :func:`parse_day_file`. This is the full read of L0 that ``reextract.py`` uses
    to rebuild the derived database from the source of truth. Yields nothing (not
    an error) when no journal exists yet, so callers can iterate unconditionally.
    """
    directory = journal_dir()
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md")):
        yield from parse_day_file(path)
