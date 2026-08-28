[CmdletBinding()]
param(
    [string]$ModelDirectory = (Join-Path $PSScriptRoot "models\Qwen3-ASR-1.7B"),
    [string]$PipIndexUrl = "https://mirrors.aliyun.com/pypi/simple/"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$ModelScope = Join-Path $PSScriptRoot ".venv\Scripts\modelscope.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Complete dependency installation first."
}

Write-Host "Installing the official ModelScope downloader..." -ForegroundColor Cyan
& $Python -m pip install --upgrade modelscope --index-url $PipIndexUrl --timeout 120 --retries 20
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install ModelScope (exit code $LASTEXITCODE)."
}

New-Item -ItemType Directory -Force -Path $ModelDirectory | Out-Null
Write-Host "Downloading Qwen/Qwen3-ASR-1.7B from ModelScope..." -ForegroundColor Cyan
Write-Host "Destination: $ModelDirectory"
Write-Host "Interrupted downloads can be resumed by running this script again."

& $ModelScope download --model Qwen/Qwen3-ASR-1.7B --local_dir $ModelDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Model download failed (exit code $LASTEXITCODE). Run this script again to resume."
}

$ConfigPath = Join-Path $ModelDirectory "config.json"
$Weights = Get-ChildItem -LiteralPath $ModelDirectory -Filter "*.safetensors" -File -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $ConfigPath) -or -not $Weights) {
    throw "The download command finished, but required model files are missing."
}

Write-Host "Model download completed." -ForegroundColor Green
Write-Host "Run .\run.bat. The local model directory will be selected automatically."
