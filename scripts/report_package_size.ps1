[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDirectory,
    [string[]]$ArchivePath = @(),
    [ValidateSet("vulkan", "cuda", "full", "unknown")]
    [string]$BuildVariant = "unknown",
    [string]$OutputDirectory = ".",
    [long]$ModelBytes = 0
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ByteTotal($Items) {
    [long]$total = 0
    foreach ($item in @($Items)) {
        if ($null -ne $item.PSObject.Properties["Length"]) {
            $total += [long]$item.Length
        } elseif ($null -ne $item.PSObject.Properties["bytes"]) {
            $total += [long]$item.bytes
        }
    }
    return $total
}

function Get-Category([string]$RelativePath) {
    $path = $RelativePath.Replace("/", "\").ToLowerInvariant()
    if ($path -match "(^|\\)(torch|torchgen)(\\|$)|cudnn|cublas|cudart|nvrtc|torch_cpu|torch_cuda") { return "PyTorch / CUDA" }
    if ($path -match "(^|\\)(transformers|qwen_asr|accelerate)(\\|$)") { return "Transformers / qwen-asr" }
    if ($path -match "(^|\\)(pyside6|shiboken6|qt)(\\|$)|qt[0-9a-z_\\.-]*\\.dll$") { return "PySide6 / Qt" }
    if ($path -like "*\bin\ffmpeg.exe" -or $path -like "*\bin\ffprobe.exe") { return "FFmpeg" }
    if ($path -match "puripulyheartgpuworker") { return "Vulkan worker" }
    if ($path -match "python(3[0-9]{2})?\\.dll$|base_library\\.zip$|python[\\/]") { return "Python runtime" }
    return "Other"
}

function Test-Forbidden([string]$RelativePath) {
    $path = $RelativePath.Replace("/", "\").ToLowerInvariant()
    return $path -match "\\.venv(\\|$)|\\(pip|wheel|pytest)_?cache(\\|$)|\\.pytest_cache(\\|$)|\\logs?(\\|$)|\\downloads?(\\|$)|\\.(gguf|safetensors|part|log|mp4|mkv|mov|avi|webm|m4v|mp3|wav|flac|m4a|aac|ogg)$|\\(media|videos?|audio)(\\|$)"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packageRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path
$outRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null

$files = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File -Force)
$inventory = foreach ($file in $files) {
    $relative = $file.FullName.Substring($packageRoot.Length).TrimStart([char[]]@('\', '/'))
    [pscustomobject]@{
        path = $relative
        bytes = [long]$file.Length
        category = Get-Category $relative
        forbidden = Test-Forbidden $relative
    }
}
$archives = foreach ($archive in $ArchivePath) {
    if (Test-Path -LiteralPath $archive) {
        $item = Get-Item -LiteralPath $archive
        [pscustomobject]@{ path = $item.FullName; bytes = [long]$item.Length }
    }
}
$trackedFiles = @()
try {
    $trackedFiles = @(git -c "safe.directory=$repoRoot" -C $repoRoot ls-files | ForEach-Object {
        $path = Join-Path $repoRoot $_
        if (Test-Path -LiteralPath $path -PathType Leaf) { Get-Item -LiteralPath $path }
    })
} catch {
    Write-Warning "Could not calculate Git tracked size: $($_.Exception.Message)"
}
$categories = @($inventory | Group-Object category | Sort-Object Name | ForEach-Object {
    [pscustomobject]@{ category = $_.Name; bytes = Get-ByteTotal $_.Group; file_count = $_.Count }
})
$forbidden = @($inventory | Where-Object forbidden | Sort-Object path)
$topFiles = @($inventory | Sort-Object bytes -Descending | Select-Object -First 100)
$ffmpegBytes = Get-ByteTotal @($inventory | Where-Object category -eq "FFmpeg")
$modelBytes = if ($ModelBytes -gt 0) { $ModelBytes } elseif ($BuildVariant -eq "vulkan") { 1692554208 } elseif ($BuildVariant -eq "cuda") { 4709120389 } else { 0 }

$report = [ordered]@{
    generated_utc = [DateTime]::UtcNow.ToString("o")
    git_repository = [ordered]@{ root = $repoRoot; tracked_bytes = Get-ByteTotal $trackedFiles; tracked_file_count = $trackedFiles.Count }
    package = [ordered]@{ path = $packageRoot; build_variant = $BuildVariant; expanded_bytes = Get-ByteTotal $files; file_count = $files.Count }
    artifact = [ordered]@{ compressed_bytes = Get-ByteTotal $archives; files = @($archives) }
    first_usable_download = [ordered]@{ package_artifact_bytes = Get-ByteTotal $archives; external_model_bytes = $modelBytes; total_bytes = (Get-ByteTotal $archives) + $modelBytes }
    ffmpeg_runtime_bytes = $ffmpegBytes
    categories = @($categories)
    largest_files = @($topFiles)
    forbidden_content = @($forbidden)
}

$jsonPath = Join-Path $outRoot "packaging-size-report.json"
$mdPath = Join-Path $outRoot "packaging-size-report.md"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding utf8

function Format-MiB([long]$Bytes) { return "{0:N2} MiB" -f ($Bytes / 1MB) }
$lines = @(
    "# QwenScribe package size report",
    "",
    "- Build variant: $BuildVariant",
    "- Git tracked size: $(Format-MiB $($report.git_repository.tracked_bytes)) ($($report.git_repository.tracked_file_count) files)",
    "- Expanded package size: $(Format-MiB $($report.package.expanded_bytes)) ($($report.package.file_count) files)",
    "- Artifact compressed size: $(Format-MiB $($report.artifact.compressed_bytes))",
    "- FFmpeg runtime: $(Format-MiB $ffmpegBytes)",
    "- External model: $(Format-MiB $modelBytes)",
    "- First usable download total: $(Format-MiB $($report.first_usable_download.total_bytes))",
    "",
    "## Categories",
    "",
    "| Category | Files | Size |",
    "|---|---:|---:|"
)
$lines += $categories | ForEach-Object { "| $($_.category) | $($_.file_count) | $(Format-MiB $($_.bytes)) |" }
$lines += @("", "## Largest 100 files", "", "| File | Size | Category |", "|---|---:|---|")
$lines += $topFiles | ForEach-Object { "| " + $_.path + " | $(Format-MiB $($_.bytes)) | $($_.category) |" }
$lines += @("", "## Forbidden content", "")
if ($forbidden.Count -eq 0) { $lines += "None detected." } else { $lines += $forbidden | ForEach-Object { "- " + $_.path } }
$lines | Set-Content -LiteralPath $mdPath -Encoding utf8

Write-Host "Wrote $jsonPath"
Write-Host "Wrote $mdPath"
if ($forbidden.Count -gt 0) { throw "Package contains forbidden content." }
