# Parameterized PyInstaller onedir build. Models are always external.
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


VARIANT = os.environ.get("QWENSCRIBE_BUILD_VARIANT", "full").strip().lower()
if VARIANT not in {"vulkan", "cuda", "full"}:
    raise SystemExit(f"Unsupported QWENSCRIBE_BUILD_VARIANT: {VARIANT!r}")

project_root = Path(SPECPATH)
runtime_hook = project_root / "scripts" / "runtime_hooks" / f"set_build_variant_{VARIANT}.py"
if not runtime_hook.is_file():
    raise SystemExit(f"Missing runtime hook: {runtime_hook}")

app_name = {
    "vulkan": "QwenScribe-Vulkan-Windows-x64",
    "cuda": "QwenScribe-CUDA-Windows-x64",
    "full": "QwenScribe-Full-Diagnostic-Windows-x64",
}[VARIANT]

local_binaries = [
    (str(project_root / "bin" / "ffmpeg.exe"), "bin"),
    (str(project_root / "bin" / "ffprobe.exe"), "bin"),
]
if VARIANT in {"vulkan", "full"}:
    local_binaries.append((str(project_root / "bin" / "PuriPulyHeartGpuWorker.exe"), "bin"))
local_binaries = [(source, target) for source, target in local_binaries if Path(source).is_file()]

qwen_datas: list[tuple[str, str]] = []
qwen_binaries: list[tuple[str, str]] = []
qwen_hiddenimports: list[str] = []
if VARIANT in {"cuda", "full"}:
    qwen_datas, qwen_binaries, qwen_hiddenimports = collect_all("qwen_asr")

vulkan_excludes = [
    "torch", "torchgen", "transformers", "qwen_asr", "accelerate",
    "gradio", "fastapi", "flask", "notebook", "jupyter",
]
cuda_excludes = ["gradio", "fastapi", "flask", "notebook", "jupyter", "vllm", "flash_attn"]
full_excludes = ["vllm", "flash_attn"]

a = Analysis(
    ["app.py"],
    pathex=[str(project_root)],
    binaries=qwen_binaries + local_binaries,
    datas=qwen_datas,
    hiddenimports=qwen_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(runtime_hook)],
    excludes={"vulkan": vulkan_excludes, "cuda": cuda_excludes, "full": full_excludes}[VARIANT],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QwenScribeDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=app_name,
)
