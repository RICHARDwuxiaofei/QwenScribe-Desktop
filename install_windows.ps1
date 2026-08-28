[CmdletBinding()]
param(
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Set-Location -LiteralPath $PSScriptRoot
Write-Host "== QwenASRDesktop Windows installer ==" -ForegroundColor Cyan

$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $PythonLauncher) {
    throw "Python Launcher (py.exe) was not found. Install 64-bit Python 3.12 first."
}

$VersionText = & py -3.12 -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"
if ($LASTEXITCODE -ne 0 -or $VersionText.Trim() -ne "3.12") {
    throw "Python 3.12 was not found. Install 64-bit Python 3.12 from python.org."
}
Write-Host "Detected Python $VersionText"

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment .venv..."
    Invoke-Checked { py -3.12 -m venv .venv }
}

. ".\.venv\Scripts\Activate.ps1"
Invoke-Checked { python -m pip install --upgrade pip setuptools wheel }

Write-Host "Installing CUDA-enabled PyTorch from: $TorchIndexUrl" -ForegroundColor Cyan
Write-Host "Override -TorchIndexUrl if the official PyTorch selector recommends another CUDA index."
Invoke-Checked { python -m pip install --upgrade torch --index-url $TorchIndexUrl }

Write-Host "Installing application dependencies..."
Invoke-Checked { python -m pip install -r requirements.txt }

$BundledFfmpeg = Test-Path -LiteralPath ".\bin\ffmpeg.exe"
$BundledFfprobe = Test-Path -LiteralPath ".\bin\ffprobe.exe"
$PathFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$PathFfprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if (($BundledFfmpeg -and $BundledFfprobe) -or ($PathFfmpeg -and $PathFfprobe)) {
    Write-Host "FFmpeg and FFprobe check passed." -ForegroundColor Green
} else {
    Write-Warning "FFmpeg and FFprobe were not both found. Restart the terminal after installing FFmpeg, or place both EXE files in .\bin."
}

$VulkanWorker = ".\bin\PuriPulyHeartGpuWorker.exe"
$VulkanModel = ".\models\Qwen3-ASR-1.7B-Q6_K.gguf"
if (Test-Path -LiteralPath $VulkanWorker) {
    Write-Host "Vulkan worker found." -ForegroundColor Green
    Invoke-Checked { & $VulkanWorker --check-startup-contract }
} else {
    Write-Warning "Vulkan worker is missing. The Vulkan/integrated-GPU backend will be unavailable."
}
if (Test-Path -LiteralPath $VulkanModel) {
    Write-Host "Local Vulkan Q6_K model found." -ForegroundColor Green
} else {
    Write-Host "Vulkan model is not bundled; the application will offer a download source when needed." -ForegroundColor Yellow
}

Write-Host "Checking PyTorch CUDA..." -ForegroundColor Cyan
@'
import torch
print("torch:", torch.__version__)
print("torch.cuda.is_available():", torch.cuda.is_available())
print("PyTorch CUDA runtime:", torch.version.cuda)
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    properties = torch.cuda.get_device_properties(0)
    print("VRAM (GiB):", round(properties.total_memory / 1024**3, 1))
else:
    print("ERROR: CUDA is unavailable. Check the NVIDIA driver and PyTorch CUDA wheel.")
'@ | python -
if ($LASTEXITCODE -ne 0) {
    throw "The PyTorch CUDA check failed to run."
}

Write-Host ""
Write-Host "Installation steps completed. Run:" -ForegroundColor Green
Write-Host "  .\run.bat"
Write-Host "The Qwen3-ASR model will be downloaded when the first transcription starts."
