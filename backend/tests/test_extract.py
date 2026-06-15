"""Unit tests for the extraction JSON parser.

The parser is the seam where a small, sometimes-messy model meets our strict
storage contract, so it gets the most direct testing. These tests pin the two
behaviors Phase 2 depends on: malformed output never crashes (it yields ``None``
so the caller can retry, then store nulls), and well-formed-but-dirty output is
recovered and normalized. No model or network is involved — ``parse_extraction``
is pure.
"""

from memory.extract import parse_extraction


def test_plain_json_is_parsed_and_typed():
    raw = '{"summary": "A normal day.", "mood": 3, "entities": ["Sam"], "themes": ["work"]}'
    out = parse_extraction(raw)
    assert out == {
        "summary": "A normal day.",
        "mood": 3,
        "entities": ["Sam"],
        "themes": ["work"],
    }


def test_recovers_json_from_markdown_fences():
    raw = '```json\n{"summary": "x", "mood": -2, "entities": [], "themes": []}\n```'
    out = parse_extraction(raw)
    assert out is not None
    assert out["mood"] == -2


def test_recovers_json_wrapped_in_prose():
    raw = (
        "Sure! Here is the extraction:\n"
        '{"summary": "x", "mood": 0, "entities": [], "themes": []}\n'
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
    assert out["entities"] == []
    assert out["themes"] == []


def test_non_list_tags_degrade_to_empty_list():
    out = parse_extraction('{"summary": "x", "entities": "Sam", "themes": null}')
    assert out["entities"] == []
    assert out["themes"] == []


def test_malformed_output_returns_none():
    assert parse_extraction("the model rambled and produced no json at all") is None
    assert parse_extraction("") is None
    assert parse_extraction("{not valid json}") is None
    assert parse_extraction("[1, 2, 3]") is None  # no JSON object present
