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


# --- Phase 3.5: stable uid + content-hash dirty-tracking ---------------------

@pytest.fixture()
def fresh_vault(tmp_path, monkeypatch):
    """An initialized empty Eva database in a temp vault (no entry yet)."""
    monkeypatch.setenv("EVA_VAULT_DIR", str(tmp_path))
    db.init_db()


def test_schema_has_phase_35_columns(fresh_vault):
    assert db.schema_is_current()  # entries.uid present after a fresh init


def test_insert_stores_uid_and_lookup_round_trips(fresh_vault):
    entry_id = db.insert_entry(
        uid="abcd1234", date="2026-06-25", entry_type="chat", text="hi",
        created_at="2026-06-25T10:00:00",
    )
    assert db.entry_id_for_uid("abcd1234") == entry_id
    assert db.entry_id_for_uid("nope") is None


def test_upsert_reuses_the_row_for_a_known_uid(fresh_vault):
    # A rebuild re-running over the same L0 entry must reuse its row (stable id),
    # updating the text in place rather than minting a second row.
    first = db.upsert_entry(
        uid="u1", date="2026-06-25", entry_type="chat", text="original",
        created_at="2026-06-25T10:00:00",
    )
    second = db.upsert_entry(
        uid="u1", date="2026-06-25", entry_type="chat", text="edited",
        created_at="2026-06-25T10:00:00",
    )
    assert first == second
    assert db.count_rows("entries") == 1
    conn = db._connect()
    assert conn.execute("SELECT text FROM entries WHERE id = ?", (first,)).fetchone()[0] == "edited"


def test_source_hash_round_trips_and_gates(fresh_vault):
    entry_id = db.insert_entry(
        uid="u2", date="2026-06-25", entry_type="chat", text="x",
        created_at="2026-06-25T10:00:00",
    )
    # No extraction yet → no hash, so a rebuild would not skip it.
    assert db.source_hash_for(entry_id) is None

    db.save_extraction(entry_id, record=_RECORD, created_at="t", source_hash="deadbeef")
    assert db.source_hash_for(entry_id) == "deadbeef"

    # Model-down path leaves the hash unset so the entry stays re-extractable.
    db.save_extraction(entry_id, record=empty_extraction(), created_at="t")
    assert db.source_hash_for(entry_id) is None
