# Eva - first-run model + runtime download (Windows).
#
# This is the ONLY part of Eva permitted to touch the network. It fetches:
#   1. the prebuilt llama.cpp CPU binaries for Windows x64, and
#   2. the Gemma GGUF model,
# into the user-owned vault (local_vault\). After this runs once, Eva is fully
# offline: the backend loads the model from this local file (-m) and never
# reaches the network again.
#
# Run from anywhere:  powershell scripts\download_model_win.ps1

$ErrorActionPreference = "Stop"

# --- Paths + model (mirror backend/llm/config.py) --------------------------
$repoRoot   = Split-Path -Parent $PSScriptRoot
$vault      = Join-Path $repoRoot "local_vault"
$runtimeDir = Join-Path $vault "runtime\llama.cpp"
$modelsDir  = Join-Path $vault "models"
# The exact GGUF (the UD-Q4_K_XL quant from the spec). We download this one file
# directly rather than via llama.cpp's -hf, which is flaky on large files and
# also pulls the multimodal projector we don't need for text chat.
$modelFile  = "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
$modelUrl   = "https://huggingface.co/unsloth/gemma-4-E2B-it-qat-GGUF/resolve/main/$modelFile"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $modelsDir  | Out-Null

# --- 1 + 2. Get the llama.cpp binaries (skip if already present) ------------
# Idempotent: if a previous run already extracted the binaries, don't re-fetch -
# just locate them and move on to the model. Makes re-runs fast and resumable.
$serverExe = Get-ChildItem -Path $runtimeDir -Recurse -Filter "llama-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $serverExe) {
    Write-Host "Resolving latest llama.cpp release ..." -ForegroundColor Cyan
    $headers = @{ "User-Agent" = "eva-downloader"; "Accept" = "application/vnd.github+json" }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" -Headers $headers

    $asset = $release.assets | Where-Object { $_.name -match "bin-win-cpu-x64\.zip$" } | Select-Object -First 1
    if (-not $asset) {
        throw "Could not find a 'bin-win-cpu-x64.zip' asset in release $($release.tag_name). Assets: $($release.assets.name -join ', ')"
    }
    Write-Host "  $($release.tag_name) -> $($asset.name)" -ForegroundColor DarkGray

    $zipPath = Join-Path $env:TEMP $asset.name
    Write-Host "Downloading llama.cpp binaries ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

    Write-Host "Extracting to $runtimeDir ..." -ForegroundColor Cyan
    Expand-Archive -Path $zipPath -DestinationPath $runtimeDir -Force
    Remove-Item $zipPath -Force

    $serverExe = Get-ChildItem -Path $runtimeDir -Recurse -Filter "llama-server.exe" | Select-Object -First 1
} else {
    Write-Host "llama.cpp binaries already present - skipping download." -ForegroundColor DarkGray
}

# Locate the executables (the zip may extract flat or into a subfolder).
$cliExe = Get-ChildItem -Path $runtimeDir -Recurse -Filter "llama-cli.exe" | Select-Object -First 1
if (-not $serverExe) { throw "llama-server.exe not found under $runtimeDir after extraction." }
if (-not $cliExe)    { throw "llama-cli.exe not found under $runtimeDir after extraction." }
Write-Host "  llama-server: $($serverExe.FullName)" -ForegroundColor DarkGray

# --- 3. Download the GGUF model directly (resumable) ------------------------
# curl.exe (built into Windows 10+) resumes partial transfers (-C -) and retries
# on flaky connections, which the model host occasionally is for multi-GB files.
$modelDest = Join-Path $modelsDir $modelFile
Write-Host "Downloading the Gemma model (this is large, ~2-3 GB; resumable) ..." -ForegroundColor Cyan
Write-Host "  $modelUrl" -ForegroundColor DarkGray
curl.exe -L --fail --retry 10 --retry-delay 5 --retry-all-errors -C - -o "$modelDest" "$modelUrl"
if ($LASTEXITCODE -ne 0) { throw "Model download failed (curl exit $LASTEXITCODE). Re-run to resume." }

# --- 4. Verify it loads (one token) -----------------------------------------
Write-Host "Verifying the model loads ..." -ForegroundColor Cyan
& $cliExe.FullName -m "$modelDest" -no-cnv -p "warmup" -n 1
if ($LASTEXITCODE -ne 0) { throw "Model loaded check failed (exit $LASTEXITCODE) - the file may be incomplete; re-run to resume." }

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Runtime : $runtimeDir"
Write-Host "  Model   : $modelDest"
Write-Host "Eva can now run fully offline."
