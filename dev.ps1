# Eva — development launcher (Phase 0).
#
# Starts the two processes you need in dev:
#   1. the Python FastAPI backend (uvicorn) on 127.0.0.1:8420
#   2. the Tauri shell, which itself starts the Vite dev server (port 1420)
#      via the `beforeDevCommand` in src-tauri/tauri.conf.json.
#
# The backend runs as a background job; when you close the Tauri window (or
# Ctrl+C this script), the backend is stopped too. This is the simple "dev
# script starts both" approach sanctioned for Phase 0 — real sidecar bundling
# comes later.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Make sure the Rust toolchain (installed via rustup into ~/.cargo) is on PATH,
# since a fresh shell may not have picked up the user-env update yet.
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $cargoBin) { $env:Path = "$cargoBin;$env:Path" }

$venvPython = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Backend venv not found. Run: python -m venv backend\.venv; backend\.venv\Scripts\pip install -r backend\requirements.txt"
}

Write-Host "Starting Eva backend on http://127.0.0.1:8420 ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath $venvPython `
    -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8420") `
    -WorkingDirectory (Join-Path $root "backend") `
    -PassThru -NoNewWindow

try {
    Write-Host "Starting Tauri shell (this compiles Rust on first run; be patient) ..." -ForegroundColor Cyan
    # Tauri must run from the repo root so it can discover src-tauri/ as a
    # subfolder (the CLI searches downward, not upward). We invoke the CLI binary
    # that npm installed under ui/, while keeping the working directory at root.
    $tauriCli = Join-Path $root "ui\node_modules\.bin\tauri.cmd"
    Push-Location $root
    try { & $tauriCli dev }
    finally { Pop-Location }
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Write-Host "Stopping Eva backend ..." -ForegroundColor Cyan
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
