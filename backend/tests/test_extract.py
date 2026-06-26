"""Unit tests for the L1 extraction parser and the L0 vault reader.

The parser is the seam where a small, sometimes-messy model meets our strict
storage contract, so it gets the most direct testing: malformed output never
crashes (it yields ``None`` so the caller can retry, then store the empty record),
and well-formed-but-dirty output is recovered and each field is normalized
independently. The vault round-trip test pins the other half of the rebuild
guarantee — that what ``append_entry`` writes, ``iter_entries`` reads back. No
model or network is involved; ``parse_extraction``/``canonicalize_entity`` are
pure and the vault writes to a temp dir.
"""

from memory import vault
from memory.extract import canonicalize_entity, empty_extraction, parse_extraction

# A fully-populated model output, used as the baseline the field tests vary from.
_FULL = (
    '{"summary": "A normal day.", "mood": 3, '
    '"emotions": [{"emotion": "joy", "intensity": 4}], '
    '"entities": [{"name": "Sam", "kind": "person"}], '
    '"themes": ["work"], "events": ["shipped the build"], '
    '"goals": ["be consistent"], "behaviors": ["coded all morning"], '
    '"decisions": ["take tomorrow off"], "open_loops": ["the Sam conversation"], '
    '"self_judgments": [{"statement": "I overdid it", "kind": "regret"}]}'
)


# --- scalar / summary fields -------------------------------------------------

def test_full_record_is_parsed_and_typed():
    out = parse_extraction(_FULL)
    assert out["summary"] == "A normal day."
    assert out["mood"] == 3
    assert out["emotions"] == [{"emotion": "joy", "intensity": 4}]
    assert out["entities"] == [{"raw": "Sam", "canonical": "sam", "kind": "person"}]
    assert out["themes"] == ["work"]
    assert out["events"] == ["shipped the build"]
    assert out["goals"] == ["be consistent"]
    assert out["behaviors"] == ["coded all morning"]
    assert out["decisions"] == ["take tomorrow off"]
    assert out["open_loops"] == [{"statement": "the Sam conversation", "status": "open"}]
    assert out["self_judgments"] == [{"statement": "I overdid it", "kind": "regret"}]


def test_recovers_json_from_markdown_fences():
    raw = '```json\n{"summary": "x", "mood": -2}\n```'
    out = parse_extraction(raw)
    assert out is not None
    assert out["mood"] == -2


def test_recovers_json_wrapped_in_prose():
    raw = (
        "Sure! Here is the extraction:\n"
        '{"summary": "x", "mood": 0}\n'
        "Let me know if you need anything else."
    )
    assert parse_extraction(raw) is not None


def test_mood_is_clamped_to_range():
    assert parse_extraction('{"summary": "x", "mood": 99}')["mood"] == 5
    assert parse_extraction('{"summary": "x", "mood": -99}')["mood"] == -5


def test_mood_coerces_string_and_float():
    assert parse_extraction('{"summary": "x", "mood": "4"}')["mood"] == 4
    assert parse_extraction('{"summary": "x", "mood": 2.0}')["mood"] == 2


def test_missing_fields_fall_back_to_safe_defaults():
    out = parse_extraction('{"summary": "only a summary"}')
    assert out["summary"] == "only a summary"
    assert out["mood"] is None
    # every list-valued field defaults to empty, matching the empty record.
    for key in ("emotions", "entities", "themes", "events", "goals", "behaviors",
                "decisions", "open_loops", "self_judgments"):
        assert out[key] == []


def test_empty_record_matches_parsed_shape():
    # The model-unavailable record must have exactly the keys the parser produces.
    assert empty_extraction().keys() == parse_extraction('{"summary": "x"}').keys()


# --- emotions (controlled set + intensity) -----------------------------------

def test_emotions_out_of_set_are_dropped():
    raw = '{"summary": "x", "emotions": [{"emotion": "joy", "intensity": 2}, {"emotion": "overwhelmed", "intensity": 5}]}'
    assert parse_extraction(raw)["emotions"] == [{"emotion": "joy", "intensity": 2}]


def test_emotion_intensity_clamped_and_nulled():
    raw = '{"summary": "x", "emotions": [{"emotion": "anger", "intensity": 9}, {"emotion": "calm", "intensity": "bad"}]}'
    out = parse_extraction(raw)["emotions"]
    assert out == [{"emotion": "anger", "intensity": 5}, {"emotion": "calm", "intensity": None}]


def test_emotions_non_list_and_non_object_degrade():
    assert parse_extraction('{"summary": "x", "emotions": "joy"}')["emotions"] == []
    assert parse_extraction('{"summary": "x", "emotions": ["joy"]}')["emotions"] == []


# --- entities (normalized objects) -------------------------------------------

def test_entity_kind_validated_and_canonicalized():
    raw = '{"summary": "x", "entities": [{"name": "Tom.", "kind": "PERSON"}, {"name": "Mars", "kind": "planet"}]}'
    out = parse_extraction(raw)["entities"]
    assert out == [
        {"raw": "Tom.", "canonical": "tom", "kind": "person"},
        {"raw": "Mars", "canonical": "mars", "kind": None},
    ]


def test_entities_non_list_and_unusable_items_dropped():
    assert parse_extraction('{"summary": "x", "entities": "Sam"}')["entities"] == []
    assert parse_extraction('{"summary": "x", "entities": ["Sam", {"name": "  "}]}')["entities"] == []


def test_canonicalize_entity_normalizes_case_space_and_punctuation():
    assert canonicalize_entity("Tom") == "tom"
    assert canonicalize_entity("  the   GYM!  ") == "the gym"
    assert canonicalize_entity('"Atlas demo".') == "atlas demo"


# --- statement lists (goals / behaviors / decisions / events) ----------------

def test_statement_lists_skip_non_strings_and_blanks():
    raw = '{"summary": "x", "goals": ["be kind", "", 5, "  "], "behaviors": "nope"}'
    out = parse_extraction(raw)
    assert out["goals"] == ["be kind"]
    assert out["behaviors"] == []


def test_goals_and_behaviors_are_kept_separate():
    # The feature-6 distinction: a stated goal and a contradicting behavior are
    # parsed into different fields, never merged.
    raw = '{"summary": "x", "goals": ["exercise daily"], "behaviors": ["skipped the gym"]}'
    out = parse_extraction(raw)
    assert out["goals"] == ["exercise daily"]
    assert out["behaviors"] == ["skipped the gym"]


# --- open loops (always open) ------------------------------------------------

def test_open_loops_default_to_open_status():
    out = parse_extraction('{"summary": "x", "open_loops": ["the unresolved fight"]}')
    assert out["open_loops"] == [{"statement": "the unresolved fight", "status": "open"}]


# --- self-judgments (object or bare string) ----------------------------------

def test_self_judgments_accept_object_and_bare_string():
    raw = '{"summary": "x", "self_judgments": [{"statement": "too harsh", "kind": "REGRET"}, "I gave up"]}'
    out = parse_extraction(raw)["self_judgments"]
    assert out == [
        {"statement": "too harsh", "kind": "regret"},
        {"statement": "I gave up", "kind": "judgment"},
    ]


def test_self_judgment_unknown_kind_defaults_to_judgment():
    raw = '{"summary": "x", "self_judgments": [{"statement": "meh", "kind": "vibes"}]}'
    assert parse_extraction(raw)["self_judgments"] == [{"statement": "meh", "kind": "judgment"}]


# --- total failure -----------------------------------------------------------

def test_malformed_output_returns_none():
    assert parse_extraction("the model rambled and produced no json at all") is None
    assert parse_extraction("") is None
    assert parse_extraction("{not valid json}") is None
    assert parse_extraction("[1, 2, 3]") is None  # no JSON object present


# --- L0 vault round-trip -----------------------------------------------------

def test_vault_round_trips_entries(tmp_path, monkeypatch):
    # Point the vault at a temp dir, write a few turns, and read them back.
    monkeypatch.setenv("EVA_VAULT_DIR", str(tmp_path))

    a = vault.append_entry("first thoughts", entry_type="chat")
    b = vault.append_entry("a goal: be more present", entry_type="journal")
    c = vault.append_entry("line one\n\nline two", entry_type="chat")  # internal blank line

    entries = list(vault.iter_entries())
    assert [e["text"] for e in entries] == [
        "first thoughts",
        "a goal: be more present",
        "line one\n\nline two",
    ]
    assert [e["type"] for e in entries] == ["chat", "journal", "chat"]
    assert all(e["date"] == a["date"] == b["date"] == c["date"] for e in entries)

    # Phase 3.5: every entry carries the stable uid minted at append time, the
    # same one the writer returned, and they are distinct per entry.
    assert [e["uid"] for e in entries] == [a["uid"], b["uid"], c["uid"]]
    assert all(e["uid"] for e in entries)
    assert len({e["uid"] for e in entries}) == 3


# --- Phase 3.5: stable uid + content hash ------------------------------------

def test_uid_is_written_into_the_header_and_round_trips(tmp_path, monkeypatch):
    # The uid lives in L0 itself, so re-reading the file recovers the exact uid the
    # writer minted — this is what lets a rebuild preserve identity.
    monkeypatch.setenv("EVA_VAULT_DIR", str(tmp_path))
    written = vault.append_entry("hello", entry_type="journal")

    day_file = vault.day_path(written["date"])
    assert f"· journal · {written['uid']}" in day_file.read_text(encoding="utf-8")
    assert vault.parse_day_file(day_file)[0]["uid"] == written["uid"]


def test_legacy_header_without_uid_parses_as_none(tmp_path, monkeypatch):
    # A pre-3.5 day-file (no uid in the header) must still parse — it comes back
    # with uid=None so the migration can stamp it, rather than failing to read.
    monkeypatch.setenv("EVA_VAULT_DIR", str(tmp_path))
    day_file = vault.day_path("2026-06-01")
    day_file.parent.mkdir(parents=True, exist_ok=True)
    day_file.write_text(
        "---\ndate: 2026-06-01\n---\n\n# Journal — 2026-06-01\n"
        "\n## 09:00:00 · chat\n\nan old entry\n",
        encoding="utf-8",
        newline="\n",
    )

    parsed = vault.parse_day_file(day_file)
    assert len(parsed) == 1
    assert parsed[0]["uid"] is None
    assert parsed[0]["text"] == "an old entry"


def test_content_hash_is_stable_and_text_sensitive():
    assert vault.content_hash("same") == vault.content_hash("same")
    assert vault.content_hash("before") != vault.content_hash("after")
