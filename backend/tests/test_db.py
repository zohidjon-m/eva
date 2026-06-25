"""Tests for the derived SQLite store's L1 fan-out and idempotency.

These exercise the half of Phase 3 the parser tests can't: that a normalized
record actually lands in the right sub-tables, that a stated goal and a
contradicting behavior are stored as *separate* rows (the feature-6 distinction),
that re-running extraction for an entry replaces rather than doubles its rows
(the rebuild idempotency ``reextract.py`` relies on), and that deleting an entry
cascades to its sub-rows. Each test runs against a throwaway database in a temp
vault — no model or network involved.
"""

import pytest

from memory import db
from memory.extract import empty_extraction

# A full record like ``parse_extraction`` produces, with a goal that contradicts
# a behavior (the feature-6 case) and one open loop.
_RECORD = {
    "summary": "Shipped late, skipped the gym.",
    "mood": -1,
    "emotions": [{"emotion": "guilt", "intensity": 4}, {"emotion": "pride", "intensity": 2}],
    "entities": [{"raw": "Tom", "canonical": "tom", "kind": "person"}],
    "themes": ["health", "work"],
    "events": ["Shipped the build", "Skipped the gym"],
    "goals": ["Put health first"],
    "behaviors": ["Skipped the gym for the third week"],
    "decisions": ["Block gym time tomorrow"],
    "open_loops": [{"statement": "Work vs health tension", "status": "open"}],
    "self_judgments": [{"statement": "Trading health for work", "kind": "judgment"}],
}


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Initialize an empty Eva database in a temp vault and return one entry id."""
    monkeypatch.setenv("EVA_VAULT_DIR", str(tmp_path))
    db.init_db()
    return db.insert_entry(
        date="2026-06-25", entry_type="chat", text="…", created_at="2026-06-25T10:00:00"
    )


def test_full_record_fans_out_into_sub_tables(fresh_db):
    db.save_extraction(fresh_db, record=_RECORD, created_at="2026-06-25T10:00:01")

    assert db.count_rows("extractions") == 1
    assert db.count_rows("emotions") == 2
    assert db.count_rows("entities") == 1
    assert db.count_rows("goals") == 1
    assert db.count_rows("behaviors") == 1
    assert db.count_rows("decisions") == 1
    assert db.count_rows("open_loops") == 1
    assert db.count_rows("self_judgments") == 1

    conn = db._connect()
    # The feature-6 distinction: goal and behavior are distinct rows in distinct tables.
    assert conn.execute("SELECT statement FROM goals").fetchone()[0] == "Put health first"
    assert conn.execute("SELECT statement FROM behaviors").fetchone()[0] == "Skipped the gym for the third week"
    # New open loops are 'open'; entity carries its canonical key.
    assert conn.execute("SELECT status FROM open_loops").fetchone()[0] == "open"
    assert tuple(conn.execute("SELECT raw, canonical, kind FROM entities").fetchone()) == ("Tom", "tom", "person")


def test_re_saving_is_idempotent(fresh_db):
    # Re-running extraction for the same entry (the reextract rebuild case) must
    # replace its rows, never double them.
    db.save_extraction(fresh_db, record=_RECORD, created_at="2026-06-25T10:00:01")
    db.save_extraction(fresh_db, record=_RECORD, created_at="2026-06-25T10:00:02")

    assert db.count_rows("extractions") == 1
    assert db.count_rows("emotions") == 2
    assert db.count_rows("goals") == 1


def test_empty_record_still_writes_one_extraction(fresh_db):
    # Model-unavailable path: exactly one (null) extraction row, no sub-rows.
    db.save_extraction(fresh_db, record=empty_extraction(), created_at="2026-06-25T10:00:01")

    assert db.count_rows("extractions") == 1
    for table in ("emotions", "entities", "goals", "behaviors", "decisions", "open_loops", "self_judgments"):
        assert db.count_rows(table) == 0


def test_deleting_entry_cascades_to_sub_rows(fresh_db):
    db.save_extraction(fresh_db, record=_RECORD, created_at="2026-06-25T10:00:01")
    conn = db._connect()
    conn.execute("DELETE FROM entries WHERE id = ?", (fresh_db,))
    conn.commit()

    for table in ("extractions", "emotions", "entities", "goals", "behaviors", "decisions", "open_loops", "self_judgments"):
        assert db.count_rows(table) == 0
