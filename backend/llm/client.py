"""Async streaming client for the local llama-server.

The other half of Eva's heart. ``stream_chat`` sends a conversation to the
OpenAI-compatible endpoint and yields Gemma's reply one token at a time, so the
UI can render words as they arrive instead of waiting for the whole answer. Keep
this module small and obvious — every chat in Eva flows through it.

All traffic is localhost (``config.endpoint()``); this client never talks to
anything but our own supervised server.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from . import config


class LlamaUnavailable(RuntimeError):
    """Raised when the local llama-server cannot be reached or errors out.

    Exists so callers (the ``WS /chat`` handler) can distinguish "the model is
    down" from a programming bug and turn it into a graceful error frame instead
    of a 500 / crashed socket.
    """


async def stream_chat(
    messages: list[dict],
    *,
    max_tokens: int = 512,
) -> AsyncIterator[str]:
    """Stream a chat completion from llama-server, yielding text tokens.

    ``messages`` is the OpenAI chat format (list of ``{"role", "content"}``). We
    request server-sent events (``stream: true``) and yield each delta's text as
    it arrives. Raises :class:`LlamaUnavailable` if the endpoint is unreachable
    or returns an error, so the streaming path fails loudly-but-gracefully rather
    than hanging. Exists because token-by-token output is the whole point of
    Phase 1 — proving Gemma streams through the backend.
    """
    payload = {
        # llama-server ignores the model name (it serves whatever is loaded), but
        # the OpenAI schema expects the field.
        "model": config.MODEL_REPO,
        "messages": messages,
        "stream": True,
        "temperature": config.TEMPERATURE,
        "top_p": config.TOP_P,
        "top_k": config.TOP_K,
        "max_tokens": max_tokens,
    }
    url = f"{config.endpoint()}/v1/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise LlamaUnavailable(
                        f"llama-server returned {resp.status_code}: {body[:200]}"
                    )
                async for line in resp.aiter_lines():
                    token = _parse_sse_line(line)
                    if token:
                        yield token
    except httpx.HTTPError as exc:  # connection refused, read error, etc.
        raise LlamaUnavailable(f"cannot reach llama-server: {exc}") from exc


async def complete_chat(
    messages: list[dict],
    *,
    max_tokens: int = 256,
    temperature: float | None = None,
) -> str:
    """Run a non-streaming chat completion and return the full reply text.

    Streaming is right for chat (words as they arrive) but wrong for extraction,
    which needs the whole JSON object at once before it can be parsed. This is the
    one-shot variant: it posts the conversation, waits, and returns
    ``choices[0].message.content``. ``temperature`` overrides the config default
    so extraction can run cold (deterministic) while chat stays warm. Raises
    :class:`LlamaUnavailable` on any transport/HTTP failure so callers treat a
    down model as "store nulls", never as a crash.
    """
    payload = {
        "model": config.MODEL_REPO,
        "messages": messages,
        "stream": False,
        "temperature": config.TEMPERATURE if temperature is None else temperature,
        "top_p": config.TOP_P,
        "top_k": config.TOP_K,
        "max_tokens": max_tokens,
    }
    url = f"{config.endpoint()}/v1/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=120.0) as http:
            resp = await http.post(url, json=payload)
            if resp.status_code != 200:
                body = resp.text
                raise LlamaUnavailable(
                    f"llama-server returned {resp.status_code}: {body[:200]}"
                )
            data = resp.json()
    except httpx.HTTPError as exc:
        raise LlamaUnavailable(f"cannot reach llama-server: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise LlamaUnavailable("llama-server returned no choices")
    return choices[0].get("message", {}).get("content", "") or ""


def _parse_sse_line(line: str) -> str | None:
    """Extract the text delta from one server-sent-event line, or ``None``.

    OpenAI-style streams send ``data: {json}`` lines plus blanks and a final
    ``data: [DONE]``. Returns the ``choices[0].delta.content`` string when
    present, else ``None``. Isolated as a small pure function so the streaming
    loop stays readable and this parsing is easy to reason about.
    """
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if data == "[DONE]":
        return None
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return None
    choices = chunk.get("choices") or []
    if not choices:
        return None
    return choices[0].get("delta", {}).get("content")
