# Parameterized PyInstaller onedir build. Models are always external.
from __future__ import annotations

import os
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


VARIANT = os.environ.get("QWENSCRIBE_BUILD_VARIANT", "full").strip().lower()
if VARIANT not in {"vulkan", "cuda", "full", "gal_cpu"}:
    raise SystemExit(f"Unsupported QWENSCRIBE_BUILD_VARIANT: {VARIANT!r}")
if VARIANT == "gal_cpu" and os.name == "nt":
    raise SystemExit("gal_cpu package is intended for Linux")

project_root = Path(SPECPATH)
runtime_hook = project_root / "scripts" / "runtime_hooks" / f"set_build_variant_{VARIANT}.py"
if not runtime_hook.is_file():
    raise SystemExit(f"Missing runtime hook: {runtime_hook}")

app_name = {
    "vulkan": "QwenScribe-Vulkan-Windows-x64",
    "cuda": "QwenScribe-CUDA-Windows-x64",
    "full": "QwenScribe-Full-Diagnostic-Windows-x64",
    "gal_cpu": "QwenScribe-GalCPU-Linux-x86_64",
}[VARIANT]

binary_suffix = ".exe" if os.name == "nt" else ""
local_binaries = [] if VARIANT == "gal_cpu" else [
    (str(project_root / "bin" / f"ffmpeg{binary_suffix}"), "bin"),
    (str(project_root / "bin" / f"ffprobe{binary_suffix}"), "bin"),
]
if VARIANT in {"vulkan", "full"}:
    local_binaries.append((str(project_root / "bin" / "PuriPulyHeartGpuWorker.exe"), "bin"))
local_binaries = [(source, target) for source, target in local_binaries if Path(source).is_file()]

qwen_datas: list[tuple[str, str]] = []
qwen_binaries: list[tuple[str, str]] = []
qwen_hiddenimports: list[str] = []
nagisa_search_path: list[str] = []
if VARIANT in {"cuda", "full", "gal_cpu"}:
    qwen_datas, qwen_binaries, qwen_hiddenimports = collect_all("qwen_asr")
    # nagisa's Cython extension imports six dynamically, beyond graph analysis.
    qwen_hiddenimports.append("six")
    # nagisa 0.2.11 uses absolute sibling imports ("import prepro") at runtime.
    # Make those modules resolvable as top-level PyInstaller modules.
    nagisa_spec = importlib.util.find_spec("nagisa")
    if nagisa_spec is not None and nagisa_spec.submodule_search_locations:
        nagisa_search_path = [str(next(iter(nagisa_spec.submodule_search_locations)))]
        qwen_hiddenimports.extend(["model", "prepro", "mecab_system_eval", "nagisa_utils", "tagger"])
        nagisa_datas, nagisa_binaries, _ = collect_all("nagisa")
        qwen_datas.extend(nagisa_datas)
        qwen_binaries.extend(nagisa_binaries)

vulkan_excludes = [
    "torch", "torchgen", "transformers", "qwen_asr", "accelerate",
    "gradio", "fastapi", "flask", "notebook", "jupyter",
]
cuda_excludes = ["gradio", "fastapi", "flask", "notebook", "jupyter", "vllm", "flash_attn"]
full_excludes = ["vllm", "flash_attn"]
gal_cpu_excludes = cuda_excludes + ["modelscope"]

a = Analysis(
    ["app.py"],
    pathex=[str(project_root), *nagisa_search_path],
    binaries=qwen_binaries + local_binaries,
    datas=qwen_datas,
    hiddenimports=qwen_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(runtime_hook)],
    excludes={"vulkan": vulkan_excludes, "cuda": cuda_excludes, "full": full_excludes, "gal_cpu": gal_cpu_excludes}[VARIANT],
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
