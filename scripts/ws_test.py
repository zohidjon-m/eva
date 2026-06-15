"""Tiny WebSocket client to prove Eva's chat streaming works.

Connects to the backend's ``WS /chat``, sends one message, and prints the reply
token-by-token as it streams in. This is the Phase 1 acceptance test: run the
backend, run this, and watch a coherent reply appear word-by-word.

Usage (with the backend running on 127.0.0.1:8420):
    python scripts/ws_test.py
    python scripts/ws_test.py "tell me a short joke"

Uses the ``websockets`` library, which is already installed as part of
``uvicorn[standard]`` in the backend venv.
"""

import asyncio
import json
import sys

import websockets

WS_URL = "ws://127.0.0.1:8420/chat"


async def main() -> None:
    """Send one message and stream the reply to stdout; report errors plainly.

    Exists as the human-runnable proof that tokens flow end-to-end. Exits with a
    non-zero status on a server-reported error so it's usable in scripts.
    """
    message = sys.argv[1] if len(sys.argv) > 1 else "hello"
    print(f"> {message}\n")

    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"message": message}))
        async for raw in ws:
            frame = json.loads(raw)
            kind = frame.get("type")
            if kind == "token":
                print(frame.get("text", ""), end="", flush=True)
            elif kind == "done":
                print("\n\n[done]")
                return
            elif kind == "error":
                print(f"\n\n[error] {frame.get('message')}")
                hint = frame.get("hint")
                if hint:
                    print(f"[hint]  {hint}")
                sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
