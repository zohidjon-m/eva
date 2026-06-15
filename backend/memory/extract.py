"""Basic L1 extraction — turn one entry into a small structured record.

This is the *only* place in Eva where the model touches raw life, and it is kept
to the smallest reliable job: read one entry and fill four fields. A 2B model is
a poor historian but a good clerk (see the memory architecture doc), so we never
ask it to reason across history here — just to summarize and tag a single entry.

The contract is strict JSON: ``{summary, mood, entities, themes}``. Two things
make this robust on a small model:
1. A few-shot prompt that shows the exact shape and forbids prose/fences.
2. A defensive parser (``parse_extraction``) that recovers JSON even when the
   model wraps it in chatter, and normalizes/clamps the fields.

If parsing fails we retry once; if it still fails (or the model is unavailable)
we return nulls. Extraction must NEVER block or undo a save — the user's words
are already safe in the vault before this ever runs.
"""

from __future__ import annotations

import json

from llm import client

# Low temperature for extraction: we want the same entry to yield stable fields,
# not creative variation. (Chat uses the spec's hotter 1.0; this is a different
# job.) A small token budget is plenty for four short fields and keeps it fast.
_EXTRACT_TEMPERATURE = 0.2
_EXTRACT_MAX_TOKENS = 256

_SYSTEM_PROMPT = (
    "You are a precise journaling extraction engine. You read one journal entry "
    "and output ONLY a single JSON object with exactly these keys: "
    '"summary" (4-5 sentence plain-English summary of what the user wrote), '
    '"mood" (one integer from -5 for very negative to +5 for very positive), '
    '"entities" (array of specific people, places, or projects mentioned), '
    '"themes" (array of short topic tags). '
    "Output the JSON object and nothing else — no explanation, no markdown fences."
)

# One worked example pins the exact shape for the model. Kept short so the prompt
# stays cheap; the schema is small enough that a single example is enough.
_FEWSHOT_USER = (
    "Entry:\n"
    "Pulled an all-nighter finishing the Atlas demo for Mara. It works but I'm "
    "wrecked and I skipped the gym again — third week running. Part of me is proud, "
    "part of me feels like I'm trading my health for this."
)
_FEWSHOT_ASSISTANT = json.dumps(
    {
        "summary": (
            "The user stayed up all night to finish the Atlas demo for Mara and got "
            "it working. They feel proud of the result but exhausted. They also "
            "skipped the gym for the third week in a row. They are conflicted about "
            "trading their health for work."
        ),
        "mood": -1,
        "entities": ["Mara", "Atlas demo", "gym"],
        "themes": ["work", "health", "self-conflict"],
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
    raising, because a malformed tag list should degrade to "no tags", never
    crash extraction. Exists to keep ``entities``/``themes`` always a clean list.
    """
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def parse_extraction(raw: str) -> dict | None:
    """Parse the model's raw output into a normalized record, or ``None``.

    Recovers the JSON object even when the model adds prose or ```` ```json ````
    fences by slicing from the first ``{`` to the last ``}``. Returns ``None``
    only when no valid JSON object can be found — that ``None`` is the signal to
    retry. When JSON *is* found but a field is missing or malformed, it is
    normalized to a safe default rather than rejected. Pure and side-effect-free
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
        "entities": _coerce_list(obj.get("entities")),
        "themes": _coerce_list(obj.get("themes")),
    }


def _empty_extraction() -> dict:
    """Return the all-null extraction stored when the model can't deliver.

    Centralizes the "we tried, nothing usable" shape so it matches the parsed
    shape exactly. Exists because storing nulls (and moving on) is the required
    fallback — a failed extraction must never cost the user their saved entry.
    """
    return {"summary": None, "mood": None, "entities": [], "themes": []}


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
    return _empty_extraction()
