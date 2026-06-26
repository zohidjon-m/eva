"""Derived SQLite store for entries and their L1 episode records.

This is a *rebuildable mirror* of the L0 vault, not a source of truth: the
Markdown on disk is authoritative, and this database exists to make the vault
queryable (full-text search, mood charts, recall, pattern mining). Delete the
file and the user loses nothing — ``scripts/reextract.py`` re-derives it from the
Markdown.

The schema is the full L1 episode record (Memory Architecture §1):
- ``entries``        — one row per captured turn (id, ``uid``, date, type, text,
  created_at). ``uid`` is the **stable, content-independent identity** (Phase 3.5):
  it is minted in L0 at write time, survives a full rebuild (``reextract.py`` reads
  it back from the Markdown rather than reassigning it), and is the key every upper
  layer's evidence pointer references — so editing an entry's text never breaks the
  pointers that cite it.
- ``extractions``    — the 1:1 scalar/summary part of an entry's L1 record
  (summary, mood, themes, events), filled in asynchronously after the save.
  ``source_hash`` records the hash of the L0 text this extraction was computed from,
  so a rebuild can **skip entries whose text is unchanged** (the hash gate) and an
  edit can be detected as "this entry is dirty, recompute it".
- Seven 1:many sub-tables keyed to ``entry_id`` hold the structured fields the
  upper layers reason over: ``emotions``, ``entities``, ``goals``, ``behaviors``,
  ``decisions``, ``open_loops``, ``self_judgments``. ``behaviors`` is kept
  structurally distinct from ``goals`` — that separation is the engine of the
  behavior-vs-goal mistake detection (feature 6).

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
    uid        TEXT UNIQUE,
    date       TEXT NOT NULL,
    type       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    entry_id    INTEGER PRIMARY KEY,
    summary     TEXT,
    mood        INTEGER,
    themes      TEXT,
    events      TEXT,
    source_hash TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- Discrete emotions (controlled vocabulary) with 1..5 intensity. One row per
-- emotion so feature-5 aggregation is plain SQL (COUNT/AVG per emotion).
CREATE TABLE IF NOT EXISTS emotions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL,
    emotion   TEXT NOT NULL,
    intensity INTEGER,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- People / places / projects. ``canonical`` is a deterministic exact-match key
-- (see extract.canonicalize_entity) so "Tom"/"tom" link now; richer semantic
-- linking is a later L3 concern.
CREATE TABLE IF NOT EXISTS entities (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL,
    raw       TEXT NOT NULL,
    canonical TEXT,
    kind      TEXT,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- Stated goals/values. Provenance is the row's own ``entry_id`` — the entry
-- that asserted it.
CREATE TABLE IF NOT EXISTS goals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL,
    statement TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- What the user actually did. Kept distinct from ``goals`` on purpose — the
-- contradiction between the two is feature 6.
CREATE TABLE IF NOT EXISTS behaviors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL,
    statement TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- Decisions / intentions the user formed in this entry.
CREATE TABLE IF NOT EXISTS decisions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL,
    statement TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- Unresolved threads. New loops are always 'open'; the updated/resolved
-- timeline is a later nightly-reconciliation phase, not written here.
CREATE TABLE IF NOT EXISTS open_loops (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL,
    statement TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- Self-judgments / regrets — signals for mistake detection. ``kind`` is
-- 'judgment' or 'regret'.
CREATE TABLE IF NOT EXISTS self_judgments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id  INTEGER NOT NULL,
    statement TEXT NOT NULL,
    kind      TEXT,
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


def insert_entry(
    *, uid: str | None = None, date: str, entry_type: str, text: str, created_at: str
) -> int:
    """Insert one captured entry and return its new row id.

    The row ``id`` is the internal join key the sub-tables use; ``uid`` is the
    stable external identity the vault minted (Phase 3.5) and the one upper layers
    reference. Takes the same ``date``/``created_at`` the vault recorded so the
    Markdown and the database describe the identical moment. Exists as the single
    write path for freshly captured turns (``reextract`` uses :func:`upsert_entry`
    so a rebuild reuses the existing row instead of minting a new id).
    """
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO entries (uid, date, type, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, date, entry_type, text, created_at),
        )
        conn.commit()
        return int(cursor.lastrowid)


def entry_id_for_uid(uid: str) -> int | None:
    """Return the row id of the entry with this ``uid``, or ``None`` if absent.

    The lookup from the stable L0 identity to the internal row id. Exists so the
    rebuild and (Phase 7.5) the single-entry recompute can find the existing row
    for a ``uid`` instead of creating a duplicate.
    """
    with closing(_connect()) as conn:
        row = conn.execute("SELECT id FROM entries WHERE uid = ?", (uid,)).fetchone()
        return int(row["id"]) if row is not None else None


def upsert_entry(
    *, uid: str, date: str, entry_type: str, text: str, created_at: str
) -> int:
    """Insert the entry for ``uid`` or update it in place; return its row id.

    Keyed on the stable ``uid``: a rebuild (or a future edit) re-running over L0
    reuses the same row — so the row ``id`` and every evidence pointer that cites
    the entry stay valid, instead of being reassigned the way a delete-and-reinsert
    would. Updating ``text`` keeps the FTS index in sync via the ``entries_au``
    trigger. Exists as the identity-preserving write path ``reextract.py`` needs.
    """
    with closing(_connect()) as conn:
        row = conn.execute("SELECT id FROM entries WHERE uid = ?", (uid,)).fetchone()
        if row is not None:
            entry_id = int(row["id"])
            conn.execute(
                "UPDATE entries SET date = ?, type = ?, text = ?, created_at = ? WHERE id = ?",
                (date, entry_type, text, created_at, entry_id),
            )
            conn.commit()
            return entry_id
        cursor = conn.execute(
            "INSERT INTO entries (uid, date, type, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, date, entry_type, text, created_at),
        )
        conn.commit()
        return int(cursor.lastrowid)


def source_hash_for(entry_id: int) -> str | None:
    """Return the ``source_hash`` stored for an entry's extraction, or ``None``.

    ``None`` means either no extraction row yet or one written while the model was
    down (which deliberately leaves the hash unset so the next rebuild re-extracts
    it). The rebuild compares this against the current L0 text hash to decide
    whether an entry is unchanged and can be skipped — the hash gate.
    """
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT source_hash FROM extractions WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        return row["source_hash"] if row is not None else None


def schema_is_current() -> bool:
    """Return whether the on-disk schema has the Phase 3.5 columns.

    A pre-3.5 database lacks the ``entries.uid`` column; ``CREATE TABLE IF NOT
    EXISTS`` can't add it to an existing table, so the rebuild detects the stale
    schema with this check and rebuilds fresh (the project's "upgrade = rebuild,
    no ALTER migration" policy). Exists so ``reextract.py`` can migrate the schema
    without a hand-written ALTER.
    """
    with closing(_connect()) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(entries)")}
        return "uid" in columns


def reset_db() -> None:
    """Delete the derived database file and recreate the current schema.

    The destructive rebuild path: because the DB is derived and rebuildable from
    L0, a schema change is handled by dropping the whole file and re-deriving, not
    by in-place migration. ``reextract.py`` calls this only when the schema is
    stale; L0 is never touched.
    """
    path = db_path()
    if path.exists():
        path.unlink()
    init_db()


# The seven sub-tables whose rows belong to one entry. ``save_extraction``
# clears these for an entry before re-inserting, so re-extraction is idempotent.
_SUB_TABLES = (
    "emotions",
    "entities",
    "goals",
    "behaviors",
    "decisions",
    "open_loops",
    "self_judgments",
)


def save_extraction(
    entry_id: int, *, record: dict, created_at: str, source_hash: str | None = None
) -> None:
    """Store (or replace) the full L1 episode record for an entry.

    ``record`` is the normalized dict from :func:`memory.extract.parse_extraction`
    / :func:`memory.extract.empty_extraction` — the single shape every code path
    produces. The whole record is written in one transaction so an entry never has
    a half-applied extraction: the scalar part goes to ``extractions`` (themes and
    events as JSON, since SQLite has no list type and they need no cross-entry
    keying), and each structured field fans out into its sub-table.

    ``source_hash`` is the hash of the L0 text this record was derived from (see
    :func:`memory.vault.content_hash`). Callers pass it **only for a real
    model-backed extraction** and leave it ``None`` when the model was down (so the
    null record is re-extracted on the next rebuild instead of being mistaken for
    up-to-date). The rebuild's hash gate reads it back via :func:`source_hash_for`.

    Idempotency is the point of the delete-then-insert: ``INSERT OR REPLACE`` keeps
    the ``extractions`` row unique by ``entry_id``, and clearing the sub-tables for
    this entry before re-inserting means re-running extraction (e.g. the whole
    ``reextract.py`` rebuild) never doubles a row. Nulls/empty lists are valid and
    expected — extraction degrades to nulls rather than blocking when the model is
    unavailable or its output won't parse, so every saved entry still gets exactly
    one record.
    """
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO extractions
                (entry_id, summary, mood, themes, events, source_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                record.get("summary"),
                record.get("mood"),
                json.dumps(record.get("themes") or []),
                json.dumps(record.get("events") or []),
                source_hash,
                created_at,
            ),
        )

        # Clear any prior sub-rows for this entry so a re-extraction replaces
        # rather than appends. Foreign keys are ON, but we delete explicitly
        # because the extractions REPLACE above doesn't cascade to these tables.
        for table in _SUB_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE entry_id = ?", (entry_id,))

        conn.executemany(
            "INSERT INTO emotions (entry_id, emotion, intensity) VALUES (?, ?, ?)",
            [(entry_id, e["emotion"], e["intensity"]) for e in record.get("emotions") or []],
        )
        conn.executemany(
            "INSERT INTO entities (entry_id, raw, canonical, kind) VALUES (?, ?, ?, ?)",
            [
                (entry_id, e["raw"], e["canonical"], e["kind"])
                for e in record.get("entities") or []
            ],
        )
        for table in ("goals", "behaviors", "decisions"):
            conn.executemany(
                f"INSERT INTO {table} (entry_id, statement) VALUES (?, ?)",
                [(entry_id, s) for s in record.get(table) or []],
            )
        conn.executemany(
            "INSERT INTO open_loops (entry_id, statement, status) VALUES (?, ?, ?)",
            [(entry_id, loop["statement"], loop["status"]) for loop in record.get("open_loops") or []],
        )
        conn.executemany(
            "INSERT INTO self_judgments (entry_id, statement, kind) VALUES (?, ?, ?)",
            [
                (entry_id, j["statement"], j["kind"])
                for j in record.get("self_judgments") or []
            ],
        )
        conn.commit()


def count_rows(table: str) -> int:
    """Return the number of rows in one table — a tiny helper for rebuild checks.

    Exists so ``reextract.py`` and the tests can assert "counts match" after a
    rebuild without each re-implementing a COUNT query. ``table`` is an internal,
    code-supplied name (never user input), so the f-string interpolation is safe.
    """
    with closing(_connect()) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


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
