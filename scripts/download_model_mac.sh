#!/usr/bin/env bash
# Eva — first-run model + runtime download (macOS).
#
# This is the ONLY part of Eva permitted to touch the network. It fetches:
#   1. the prebuilt llama.cpp binaries for macOS (arm64), and
#   2. the Gemma GGUF model,
# into the user-owned vault (local_vault/). After this runs once, Eva is fully
# offline: the backend launches llama-server with --offline and never reaches
# out again.
#
# Run from anywhere:  bash scripts/download_model_mac.sh
#
# NOTE: written for parity with the Windows script; not yet tested on macOS.
set -euo pipefail

# --- Paths (mirror backend/llm/config.py) ----------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VAULT="$REPO_ROOT/local_vault"
RUNTIME_DIR="$VAULT/runtime/llama.cpp"
MODELS_DIR="$VAULT/models"
# The exact GGUF (UD-Q4_K_XL quant). Downloaded directly rather than via
# llama.cpp's -hf, which is flaky on large files and also pulls the multimodal
# projector we don't need for text chat.
MODEL_FILE="gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
MODEL_URL="https://huggingface.co/unsloth/gemma-4-E2B-it-qat-GGUF/resolve/main/$MODEL_FILE"

mkdir -p "$RUNTIME_DIR" "$MODELS_DIR"

# Pick the asset for this Mac's architecture.
ARCH="$(uname -m)"  # arm64 or x86_64
if [ "$ARCH" = "arm64" ]; then
  ASSET_PATTERN="bin-macos-arm64.zip"
else
  ASSET_PATTERN="bin-macos-x64.zip"
fi

# --- 1. Resolve the latest llama.cpp macOS release --------------------------
echo "Resolving latest llama.cpp release ..."
RELEASE_JSON="$(curl -fsSL -H 'User-Agent: eva-downloader' \
  https://api.github.com/repos/ggml-org/llama.cpp/releases/latest)"
ASSET_URL="$(printf '%s' "$RELEASE_JSON" \
  | grep -o '"browser_download_url": *"[^"]*'"$ASSET_PATTERN"'"' \
  | head -n1 | sed 's/.*"\(https[^"]*\)"$/\1/')"
if [ -z "$ASSET_URL" ]; then
  echo "Could not find a '$ASSET_PATTERN' asset in the latest release." >&2
  exit 1
fi
echo "  -> $ASSET_URL"

# --- 2. Download + extract the binaries -------------------------------------
ZIP_PATH="$(mktemp -t llamacpp).zip"
echo "Downloading llama.cpp binaries ..."
curl -fSL "$ASSET_URL" -o "$ZIP_PATH"
echo "Extracting to $RUNTIME_DIR ..."
unzip -o "$ZIP_PATH" -d "$RUNTIME_DIR" >/dev/null
rm -f "$ZIP_PATH"

CLI_BIN="$(find "$RUNTIME_DIR" -name 'llama-cli' -type f | head -n1)"
SERVER_BIN="$(find "$RUNTIME_DIR" -name 'llama-server' -type f | head -n1)"
if [ -z "$CLI_BIN" ] || [ -z "$SERVER_BIN" ]; then
  echo "llama-cli / llama-server not found under $RUNTIME_DIR after extraction." >&2
  exit 1
fi
chmod +x "$CLI_BIN" "$SERVER_BIN"

# --- 3. Download the GGUF model directly (resumable) ------------------------
# curl resumes partial transfers (-C -) and retries on flaky connections, which
# the model host occasionally is for multi-GB files.
MODEL_DEST="$MODELS_DIR/$MODEL_FILE"
echo "Downloading the Gemma model (this is large, ~2-3 GB; resumable) ..."
echo "  $MODEL_URL"
curl -L --fail --retry 10 --retry-delay 5 --retry-all-errors -C - -o "$MODEL_DEST" "$MODEL_URL"

# --- 4. Verify it loads (one token) -----------------------------------------
echo "Verifying the model loads ..."
"$CLI_BIN" -m "$MODEL_DEST" -no-cnv -p "warmup" -n 1

echo ""
echo "Done."
echo "  Runtime : $RUNTIME_DIR"
echo "  Model   : $MODEL_DEST"
echo "Eva can now run fully offline."
