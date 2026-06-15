"""Derived SQLite store for entries and their extractions.

This is a *rebuildable mirror* of the L0 vault, not a source of truth: the
Markdown on disk is authoritative, and this database exists to make the vault
queryable (full-text search now; mood charts and recall later). Delete the file
and the user loses nothing — Phase later can re-derive it from the Markdown.

Two tables for Phase 2:
- ``entries``      — one row per captured turn (id, date, type, text, created_at)
- ``extractions``  — the basic L1 record for an entry (summary, mood, entities,
  themes), filled in asynchronously after the entry is saved.

Plus an FTS5 index over ``entries.text`` so search is fast and offline.

Each public call opens its own short-lived connection. SQLite connections aren't
safe to share across threads, and Eva writes from both the request path and a
background extraction task — a fresh connection per call is the simplest thing
that is correct.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from llm import config

# Schema is created on demand and guarded by ``IF NOT EXISTS`` so ``init_db`` is
# safe to call on every startup. The FTS table is kept in sync with ``entries``
# by triggers (the standard external-content FTS5 pattern) so search results can
# never drift from the real rows.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    type       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    entry_id   INTEGER PRIMARY KEY,
    summary    TEXT,
    mood       INTEGER,
    entities   TEXT,
    themes     TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
    USING fts5(text, content='entries', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO entries_fts(rowid, text) VALUES (new.id, new.text);
END;
"""


def db_path() -> Path:
    """Return the path to the SQLite database file inside the vault.

    Kept beside the journal (``local_vault/eva.db``) so all of Eva's on-disk
    state is one user-owned, deletable folder. Exists so every connection agrees
    on one location.
    """
    return config.vault_dir() / "eva.db"


def _connect() -> sqlite3.Connection:
    """Open a fresh connection with Eva's standard settings.

    Enables foreign keys (off by default in SQLite) so ``ON DELETE CASCADE`` from
    entries to extractions actually fires, and sets ``Row`` so callers read
    columns by name. Internal helper so every entry point is configured the same.
    """
    db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the schema if it doesn't exist; safe to call repeatedly.

    Called once at backend startup so the first chat turn has somewhere to land.
    Idempotent (all DDL is ``IF NOT EXISTS``), so it never destroys existing data.
    """
    with closing(_connect()) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def insert_entry(*, date: str, entry_type: str, text: str, created_at: str) -> int:
    """Insert one captured entry and return its new row id.

    The id is the join key the background extraction uses to attach its result.
    Takes the same ``date``/``created_at`` the vault recorded so the Markdown and
    the database describe the identical moment. Exists as the single write path
    for captured turns.
    """
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO entries (date, type, text, created_at) VALUES (?, ?, ?, ?)",
            (date, entry_type, text, created_at),
        )
        conn.commit()
        return int(cursor.lastrowid)


def save_extraction(
    entry_id: int,
    *,
    summary: str | None,
    mood: int | None,
    entities: list | None,
    themes: list | None,
    created_at: str,
) -> None:
    """Store (or replace) the L1 extraction for an entry.

    ``entities``/``themes`` are serialized to JSON text — SQLite has no native
    list type and JSON keeps them readable and trivially re-parsed. Uses
    ``INSERT OR REPLACE`` keyed on ``entry_id`` so a retry can't create a second
    row for the same entry. Nulls are valid and expected: extraction stores nulls
    rather than blocking when the model is unavailable or its output won't parse.
    """
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO extractions
                (entry_id, summary, mood, entities, themes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                summary,
                mood,
                json.dumps(entities) if entities is not None else None,
                json.dumps(themes) if themes is not None else None,
                created_at,
            ),
        )
        conn.commit()


def search(query: str, *, limit: int = 20) -> list[sqlite3.Row]:
    """Full-text search over captured entries, newest match first.

    Thin wrapper over the FTS5 index — the reason FTS exists at all. Returns the
    matching ``entries`` rows. Provided now so the index is proven end-to-end;
    richer recall is built on top of it in later phases.
    """
    with closing(_connect()) as conn:
        return conn.execute(
            """
            SELECT e.*
            FROM entries_fts f
            JOIN entries e ON e.id = f.rowid
            WHERE entries_fts MATCH ?
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
