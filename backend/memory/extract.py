"""Full L1 extraction — turn one entry into a complete episode record.

This is the *only* place in Eva where the model touches raw life, and it is still
kept to one bounded, low-temperature job: read one entry and fill the fields of
the Memory Architecture §1 episode record. A 2B model is a poor historian but a
good clerk, so we never ask it to reason across history here — just to summarize
and structure a single entry. Everything that counts or connects across entries
is deterministic code in later layers.

The contract is strict JSON with these keys: ``summary``, ``mood``, ``emotions``,
``entities``, ``themes``, ``events``, ``goals``, ``behaviors``, ``decisions``,
``open_loops``, ``self_judgments``. Two things keep this robust on a small model
even as the schema grows (the schema-degradation guard, §5.6):
1. One tight few-shot prompt with a single richly-populated worked example.
2. A defensive parser (``parse_extraction``) that recovers JSON from chatter and
   normalizes *each field independently*, so one malformed field never sinks the
   rest or crashes the call.

If parsing fails entirely we retry once; if it still fails (or the model is
unavailable) we return the empty record. Extraction must NEVER block or undo a
save — the user's words are already safe in the vault before this ever runs.
"""

from __future__ import annotations

import json
import re

from llm import client

# Low temperature for extraction: we want the same entry to yield stable fields,
# not creative variation. (Chat uses the spec's hotter 1.0; this is a different
# job.) The token budget covers the full record for a normal entry and keeps it
# fast; a larger schema needs more room than Phase 2's four fields.
_EXTRACT_TEMPERATURE = 0.2
_EXTRACT_MAX_TOKENS = 512

# The controlled emotion vocabulary (Memory Architecture §1: "a small controlled
# set"). Extraction keeps only emotions in this set so feature-5 aggregation runs
# over a stable, closed vocabulary; anything the model invents outside it is
# dropped rather than polluting the time-series. Grow this deliberately, not ad
# hoc — every name here is a column the analytics can count on existing forever.
EMOTION_SET = frozenset(
    {
        "anger",
        "shame",
        "joy",
        "anxiety",
        "calm",
        "sadness",
        "fear",
        "love",
        "pride",
        "guilt",
        "gratitude",
        "loneliness",
        "hope",
        "frustration",
        "contentment",
    }
)

# The allowed entity kinds. Unknown kinds normalize to ``None`` rather than being
# invented, so the column stays trustworthy.
_ENTITY_KINDS = frozenset({"person", "place", "project"})

_SYSTEM_PROMPT = (
    "You are a precise journaling extraction engine. You read one journal entry "
    "and output ONLY a single JSON object with exactly these keys:\n"
    '"summary": 4-5 sentence plain-English summary of what the user wrote.\n'
    '"mood": one integer from -5 (very negative) to +5 (very positive).\n'
    '"emotions": array of {"emotion","intensity"}; emotion is ONE of '
    "anger, shame, joy, anxiety, calm, sadness, fear, love, pride, guilt, "
    "gratitude, loneliness, hope, frustration, contentment; intensity is an "
    "integer 1-5. Use only emotions actually present.\n"
    '"entities": array of {"name","kind"} for specific people, places, or '
    'projects mentioned; kind is "person", "place", or "project".\n'
    '"themes": array of short topic tags.\n'
    '"events": array of short phrases for what actually happened.\n'
    '"goals": array of what the user says they want to be or do (stated '
    "goals/values).\n"
    '"behaviors": array of what the user actually did (keep separate from '
    "goals, even when they contradict).\n"
    '"decisions": array of decisions or intentions the user formed.\n'
    '"open_loops": array of unresolved threads or feelings still hanging.\n'
    '"self_judgments": array of {"statement","kind"} where kind is "judgment" '
    'or "regret".\n'
    "Use [] for any field with nothing to report. Output the JSON object and "
    "nothing else — no explanation, no markdown fences."
)

# One worked example pins the exact shape for the model. A single richly-populated
# entry is worth more than many thin ones on a small model: it shows every field
# at once, including the goal-vs-behavior split (wants to stay healthy / skipped
# the gym) that feature 6 depends on.
_FEWSHOT_USER = (
    "Entry:\n"
    "Pulled an all-nighter finishing the Atlas demo for Mara. It works but I'm "
    "wrecked and I skipped the gym again — third week running. I keep telling "
    "myself health comes first, then I do this. I've decided to actually block "
    "gym time on my calendar tomorrow. Part of me is proud, part of me feels "
    "like I'm trading my health for this."
)
_FEWSHOT_ASSISTANT = json.dumps(
    {
        "summary": (
            "The user stayed up all night to finish the Atlas demo for Mara and got "
            "it working. They feel proud of the result but exhausted. They also "
            "skipped the gym for the third week in a row, which clashes with their "
            "stated value that health comes first. They decided to block gym time on "
            "their calendar tomorrow and feel conflicted about trading health for work."
        ),
        "mood": -1,
        "emotions": [
            {"emotion": "pride", "intensity": 3},
            {"emotion": "guilt", "intensity": 4},
        ],
        "entities": [
            {"name": "Mara", "kind": "person"},
            {"name": "Atlas demo", "kind": "project"},
            {"name": "gym", "kind": "place"},
        ],
        "themes": ["work", "health", "self-conflict"],
        "events": ["Finished the Atlas demo", "Skipped the gym again"],
        "goals": ["Put health first"],
        "behaviors": ["Skipped the gym for the third week running"],
        "decisions": ["Block gym time on the calendar tomorrow"],
        "open_loops": ["Tension between work and taking care of health"],
        "self_judgments": [
            {"statement": "Feels like trading health for work", "kind": "judgment"}
        ],
    }
)


def _coerce_mood(value: object) -> int | None:
    """Coerce a model-supplied mood into an int clamped to [-5, +5], or ``None``.

    The model sometimes returns ``"3"``, ``3.0``, or an out-of-range number;
    callers downstream (mood charts) need a clean integer or a clear null. Exists
    so that contract is enforced in one place rather than at every read site.
    """
    try:
        number = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(-5, min(5, number))


def _coerce_list(value: object) -> list[str]:
    """Coerce a field into a list of non-empty strings; default to ``[]``.

    Tolerates the model returning a non-list (or list of non-strings) without
    raising, because a malformed list should degrade to "nothing", never crash
    extraction. Shared by every plain string-list field (``themes``, ``events``,
    ``goals``, ``behaviors``, ``decisions``).
    """
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            continue  # a stray number/object is noise, not a tag — skip it
        text = item.strip()
        if text:
            cleaned.append(text)
    return cleaned


def canonicalize_entity(name: str) -> str:
    """Return a deterministic exact-match key for an entity name.

    Casefolds, trims, collapses internal whitespace, and strips surrounding
    punctuation so "Tom", "tom", and "Tom." all map to the same key and can be
    linked across entries by a plain equality join from day one. This is *only*
    deterministic normalization — semantic linking (recognizing that "my brother"
    and "Tom" are the same person) is L3 identity resolution and explicitly out of
    scope here; this function just guarantees the ``canonical`` column exists and
    is stable so that later work has something to build on.
    """
    lowered = name.casefold().strip()
    collapsed = re.sub(r"\s+", " ", lowered)
    return collapsed.strip(" \t\n\r.,;:!?\"'()[]{}")


def _coerce_emotions(value: object) -> list[dict]:
    """Coerce ``emotions`` into ``[{emotion, intensity}]`` over the controlled set.

    Keeps only objects whose ``emotion`` (casefolded) is in :data:`EMOTION_SET`,
    clamping ``intensity`` to 1..5 (missing/unparseable → ``None``). Out-of-set
    emotions and malformed items are dropped, never invented or crashed on, so the
    feature-5 time-series only ever sees vocabulary it can aggregate.
    """
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("emotion")
        if not isinstance(name, str):
            continue
        key = name.casefold().strip()
        if key not in EMOTION_SET:
            continue
        cleaned.append({"emotion": key, "intensity": _coerce_intensity(item.get("intensity"))})
    return cleaned


def _coerce_intensity(value: object) -> int | None:
    """Coerce an emotion intensity into an int clamped to [1, 5], or ``None``.

    Mirrors ``_coerce_mood`` for the emotion scale: the model may send ``"3"`` or
    ``4.0`` or something unusable; this yields a clean 1..5 or a clear null.
    """
    try:
        number = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(1, min(5, number))


def _coerce_entities(value: object) -> list[dict]:
    """Coerce ``entities`` into ``[{raw, canonical, kind}]``; default to ``[]``.

    Each item needs a usable ``name`` (anything else is dropped); ``kind`` is kept
    only if it is one of person/place/project, else ``None`` rather than invented.
    ``canonical`` is filled by :func:`canonicalize_entity` so the cross-entry link
    key is populated at write time.
    """
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        raw = name.strip()
        canonical = canonicalize_entity(raw)
        if not canonical:
            continue
        kind = item.get("kind")
        kind = kind if isinstance(kind, str) and kind.casefold() in _ENTITY_KINDS else None
        cleaned.append({"raw": raw, "canonical": canonical, "kind": kind.casefold() if kind else None})
    return cleaned


def _coerce_open_loops(value: object) -> list[dict]:
    """Coerce ``open_loops`` into ``[{statement, status}]``; default to ``[]``.

    Each loop is a non-empty statement; ``status`` is always ``"open"`` at
    extraction time (a newly-noticed thread). The updated/resolved timeline is a
    later nightly-reconciliation concern, so we never read a status from the model.
    """
    return [{"statement": s, "status": "open"} for s in _coerce_list(value)]


def _coerce_self_judgments(value: object) -> list[dict]:
    """Coerce ``self_judgments`` into ``[{statement, kind}]``; default to ``[]``.

    Accepts either ``{"statement","kind"}`` objects (``kind`` normalized to
    'judgment'/'regret', else 'judgment') or bare strings (treated as a judgment),
    so a small model that flattens the shape still yields usable rows.
    """
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        if isinstance(item, str):
            statement, kind = item.strip(), "judgment"
        elif isinstance(item, dict):
            raw_statement = item.get("statement")
            statement = raw_statement.strip() if isinstance(raw_statement, str) else ""
            raw_kind = item.get("kind")
            kind = raw_kind.casefold() if isinstance(raw_kind, str) else ""
            kind = kind if kind in {"judgment", "regret"} else "judgment"
        else:
            continue
        if statement:
            cleaned.append({"statement": statement, "kind": kind})
    return cleaned


def parse_extraction(raw: str) -> dict | None:
    """Parse the model's raw output into a normalized full record, or ``None``.

    Recovers the JSON object even when the model adds prose or ```` ```json ````
    fences by slicing from the first ``{`` to the last ``}``. Returns ``None``
    only when no valid JSON object can be found at all — that ``None`` is the
    signal to retry. When JSON *is* found, every field is normalized independently
    by its own coercer, so a single missing or malformed field degrades to a safe
    default instead of rejecting the whole extraction. Pure and side-effect-free
    so it is the unit-testable heart of this module.
    """
    if not raw or not isinstance(raw, str):
        return None

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None

    summary = obj.get("summary")
    summary = summary.strip() if isinstance(summary, str) and summary.strip() else None

    return {
        "summary": summary,
        "mood": _coerce_mood(obj.get("mood")),
        "emotions": _coerce_emotions(obj.get("emotions")),
        "entities": _coerce_entities(obj.get("entities")),
        "themes": _coerce_list(obj.get("themes")),
        "events": _coerce_list(obj.get("events")),
        "goals": _coerce_list(obj.get("goals")),
        "behaviors": _coerce_list(obj.get("behaviors")),
        "decisions": _coerce_list(obj.get("decisions")),
        "open_loops": _coerce_open_loops(obj.get("open_loops")),
        "self_judgments": _coerce_self_judgments(obj.get("self_judgments")),
    }


def empty_extraction() -> dict:
    """Return the empty record stored when the model can't deliver.

    Centralizes the "we tried, nothing usable" shape so it matches the parsed
    record exactly. Used both here (parse failure) and by the caller when the
    model is unavailable, so every saved entry still gets exactly one record — a
    failed extraction must never cost the user their saved entry.
    """
    return {
        "summary": None,
        "mood": None,
        "emotions": [],
        "entities": [],
        "themes": [],
        "events": [],
        "goals": [],
        "behaviors": [],
        "decisions": [],
        "open_loops": [],
        "self_judgments": [],
    }


def _build_messages(text: str) -> list[dict]:
    """Assemble the few-shot extraction prompt for one entry.

    System rules + one worked example + the real entry, in the OpenAI chat shape
    the local server expects. Isolated so the prompt is easy to read and tune in
    one spot — prompt quality is most of extraction quality on a small model.
    """
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _FEWSHOT_USER},
        {"role": "assistant", "content": _FEWSHOT_ASSISTANT},
        {"role": "user", "content": f"Entry:\n{text.strip()}"},
    ]


async def extract(text: str) -> dict:
    """Extract ``{summary, mood, entities, themes}`` from one entry's text.

    Makes one bounded model call; if the output won't parse, retries exactly once
    (small models occasionally emit a stray token); if it still won't parse, or
    the model is unavailable, returns nulls. Never raises into the caller — the
    background task that runs this must always be able to store *something* and
    leave the saved entry untouched.
    """
    messages = _build_messages(text)
    for _attempt in range(2):  # original try + one retry
        try:
            raw = await client.complete_chat(
                messages,
                max_tokens=_EXTRACT_MAX_TOKENS,
                temperature=_EXTRACT_TEMPERATURE,
            )
        except client.LlamaUnavailable:
            break  # model down — don't hammer it; fall through to nulls
        parsed = parse_extraction(raw)
        if parsed is not None:
            return parsed
    return empty_extraction()
