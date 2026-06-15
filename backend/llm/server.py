"""Supervise the native ``llama-server`` process.

This is one half of Eva's heart (the other is ``client.py``). It owns the single
``llama-server`` child: starting it with the right model and parameters, knowing
whether it is alive and ready, and stopping it cleanly. It never raises into the
request path — instead it reports structured state so the backend can show a
graceful "model not found" / "starting up" message and never crash.

Privacy: the child is bound to ``127.0.0.1`` and launched with ``--offline`` so
it cannot reach the network at runtime. The only permitted download lives in the
first-run scripts, never here.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import httpx

from . import config

# The single supervised child. Module-level because there is exactly one
# llama-server for the whole backend; a class would imply multiple instances we
# never want.
_process: subprocess.Popen | None = None

# Serialize start attempts so two concurrent chat turns can't spawn two servers.
_start_lock = asyncio.Lock()

# How long to wait for llama-server to load the model and answer /health before
# giving up. CPU model load can take a while on first launch.
_READY_TIMEOUT_S = 120.0
_READY_POLL_INTERVAL_S = 0.5


def download_command() -> str:
    """Return the OS-appropriate first-run download command, as a hint string.

    Shown in ``/health`` and chat-error frames when the binary or model is
    missing, so the user knows exactly how to fix it. Exists so the failure path
    is actionable, not a dead end.
    """
    if os.name == "nt":
        return "powershell scripts\\download_model_win.ps1"
    return "bash scripts/download_model_mac.sh"


def _port_open() -> bool:
    """Return whether something is listening on the llama-server port.

    A cheap liveness probe used by ``is_running``; avoids importing the model
    just to check. Exists because a live process handle alone doesn't prove the
    server is actually accepting connections.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((config.LLAMA_HOST, config.LLAMA_PORT)) == 0


def is_running() -> bool:
    """Return whether our supervised llama-server is up and accepting connections.

    True only when we hold a live child process *and* its port is open. Exists so
    callers can decide whether a (re)start is needed without guessing.
    """
    global _process
    if _process is not None and _process.poll() is not None:
        # Child exited; drop the stale handle so we'll restart cleanly.
        _process = None
    return _process is not None and _port_open()


def status() -> dict:
    """Report current readiness as a plain dict for ``/health``.

    Pure and non-throwing: it inspects disk + process state only. This is the
    backend's single truth source for "is Eva ready, and if not, what's missing?"
    """
    binary = config.llama_server_bin()
    return {
        "status": "ok",
        "binary_present": binary is not None,
        "model_present": config.model_present(),
        "llama_running": is_running(),
        "endpoint": config.endpoint(),
        "download_command": download_command(),
    }


def _spawn() -> subprocess.Popen:
    """Launch llama-server with Eva's model and parameters; return the handle.

    Internal helper for ``ensure_running``. Encodes the launch command in one
    place: localhost bind and the spec's sampling params. Loads the model from a
    concrete local file with ``-m`` — no ``-hf``/network path is ever invoked, so
    the runtime is offline by construction (the model was fetched once by the
    first-run download script).
    """
    binary = config.llama_server_bin()
    if binary is None:
        raise FileNotFoundError("llama-server binary not found")
    model = config.model_path()
    if model is None:
        raise FileNotFoundError("model GGUF not found")

    args = [
        str(binary),
        "--host", config.LLAMA_HOST,
        "--port", str(config.LLAMA_PORT),
        "-m", str(model),
        "--jinja",
        "--ctx-size", str(config.CTX_SIZE),
        "--temp", str(config.TEMPERATURE),
        "--top-p", str(config.TOP_P),
        "--top-k", str(config.TOP_K),
    ]

    # Inherit stdout/stderr so llama-server logs land in the backend console —
    # useful in dev. No log files are written (nothing to leak).
    return subprocess.Popen(args, env=dict(os.environ), stdout=sys.stdout, stderr=sys.stderr)


async def _wait_ready() -> bool:
    """Poll llama-server's /health until it responds OK or we time out.

    Returns True once the model is loaded and serving. Exists so chat turns wait
    for a genuinely ready server instead of racing a half-started one.
    """
    deadline = asyncio.get_event_loop().time() + _READY_TIMEOUT_S
    url = f"{config.endpoint()}/health"
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            # Stop early if the child died during startup.
            if _process is not None and _process.poll() is not None:
                return False
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass  # not up yet; keep polling
            await asyncio.sleep(_READY_POLL_INTERVAL_S)
    return False


async def ensure_running() -> dict:
    """Start llama-server if needed and wait until it's ready; report the outcome.

    Idempotent and safe to call before every chat turn: returns immediately if
    already serving. Returns a status dict with an ``error``/``hint`` when the
    binary or model is missing or startup fails — it never raises into the chat
    path, so a missing model degrades gracefully instead of crashing the socket.
    """
    global _process

    if is_running():
        return {"ready": True, **status()}

    if config.llama_server_bin() is None:
        return {
            "ready": False,
            "error": "llama-server binary not found",
            "hint": download_command(),
            **status(),
        }
    if not config.model_present():
        return {
            "ready": False,
            "error": "model not found",
            "hint": download_command(),
            **status(),
        }

    async with _start_lock:
        # Re-check inside the lock: another coroutine may have started it.
        if is_running():
            return {"ready": True, **status()}
        try:
            _process = _spawn()
        except FileNotFoundError:
            return {
                "ready": False,
                "error": "llama-server binary not found",
                "hint": download_command(),
                **status(),
            }
        ready = await _wait_ready()

    if not ready:
        stop()
        return {
            "ready": False,
            "error": "llama-server failed to start in time",
            "hint": download_command(),
            **status(),
        }
    return {"ready": True, **status()}


def stop() -> None:
    """Terminate the supervised llama-server child, if any.

    Called on backend shutdown so we don't leak an orphaned model process.
    Best-effort: escalates to kill if it doesn't exit promptly.
    """
    global _process
    if _process is None:
        return
    proc, _process = _process, None
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
