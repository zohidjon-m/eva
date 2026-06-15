"""Central configuration for Eva's LLM subsystem.

One source of truth for ports, the model identifier, generation parameters, and
where the runtime binary and model file live on disk. ``server.py``,
``client.py``, ``app.py``, and the download scripts all agree by reading from
here — so changing a port or a path is a one-line edit, not a hunt.

Privacy note: everything here is localhost-only. The model and binary live
inside the user-owned vault; nothing is global to the machine.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# --- Network ---------------------------------------------------------------
# llama-server binds here; the backend is the only thing that talks to it.
LLAMA_HOST = "127.0.0.1"
LLAMA_PORT = 11500

# --- Model -----------------------------------------------------------------
# The Phase 1 spec names ``unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL``. We pin
# the concrete GGUF file rather than relying on llama.cpp's ``-hf`` downloader:
# that downloader is flaky on large files and also pulls the multimodal
# ``mmproj`` projector we don't need for text chat. Instead the download scripts
# fetch this one file directly, and the server loads it with ``-m``.
MODEL_REPO = "unsloth/gemma-4-E2B-it-qat-GGUF"
MODEL_FILE = "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
# Direct HuggingFace download URL (used only by the first-run scripts).
MODEL_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILE}"

# --- Generation params (from the spec) -------------------------------------
# Gemma has no "thinking" mode toggle, so thinking-OFF simply means we never
# enable any reasoning preamble — these sampling params are all there is.
TEMPERATURE = 1.0
TOP_P = 0.95
TOP_K = 64
# A modest context budget keeps CPU load + memory sane for Phase 1. The real
# context strategy (memory injection, budgets) is a later phase's concern.
CTX_SIZE = 4096


def vault_dir() -> Path:
    """Return the Eva vault directory (user-owned data + runtime + model).

    Defaults to ``<repo_root>/local_vault`` (gitignored). Overridable via the
    ``EVA_VAULT_DIR`` env var so packaging/tests can relocate it. Exists so that
    every path in Eva derives from one place — the vault is the boundary of all
    on-disk state.
    """
    override = os.environ.get("EVA_VAULT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # config.py is backend/llm/config.py, so repo root is three parents up.
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "local_vault"


def models_dir() -> Path:
    """Return the directory that holds the GGUF model file.

    Used as ``LLAMA_CACHE`` so llama.cpp's ``-hf`` download lands here. Exists so
    the model lives inside the vault (user-owned, deletable) rather than in a
    machine-global cache.
    """
    return vault_dir() / "models"


def runtime_dir() -> Path:
    """Return the directory that holds the extracted llama.cpp binaries.

    The first-run download script unzips the prebuilt release here. Exists so the
    runtime is vault-local and the app install itself stays small.
    """
    return vault_dir() / "runtime" / "llama.cpp"


def llama_server_bin() -> Path | None:
    """Locate the ``llama-server`` executable, or ``None`` if not installed yet.

    Resolution order: ``EVA_LLAMA_SERVER_BIN`` env override → the vault runtime
    dir (where the download script puts it) → the system ``PATH``. Returning
    ``None`` instead of raising lets the backend report a graceful "binary not
    found" state rather than crashing.
    """
    override = os.environ.get("EVA_LLAMA_SERVER_BIN")
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None

    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    # The release zip may extract flat or into a build/bin subdir; check both.
    for candidate in (runtime_dir() / exe, runtime_dir() / "build" / "bin" / exe):
        if candidate.is_file():
            return candidate

    found = shutil.which("llama-server")
    return Path(found) if found else None


def model_path() -> Path | None:
    """Return the path to the GGUF model file in the vault, or ``None``.

    Prefers the exact ``MODEL_FILE`` we download; falls back to any ``*.gguf``
    under the models dir so a hand-placed model still works. Returns ``None`` when
    nothing is there. Exists so the supervisor has one concrete path to pass to
    ``llama-server -m`` and ``/health`` has one definition of "model present".
    """
    expected = models_dir() / MODEL_FILE
    if expected.is_file():
        return expected
    if models_dir().is_dir():
        for found in models_dir().rglob("*.gguf"):
            return found
    return None


def model_present() -> bool:
    """Return whether a GGUF model file exists in the vault.

    Thin wrapper over :func:`model_path` so callers reading like a question
    (``if model_present()``) stay readable. The single truth for model readiness.
    """
    return model_path() is not None


def endpoint() -> str:
    """Return the base URL of the local llama-server OpenAI-compatible API.

    Exists so the client never hardcodes the host/port and we keep it localhost.
    """
    return f"http://{LLAMA_HOST}:{LLAMA_PORT}"
