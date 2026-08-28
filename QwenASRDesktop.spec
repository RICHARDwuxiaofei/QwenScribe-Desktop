# Optional PyInstaller onedir build. The model weights are intentionally external.
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

qwen_datas, qwen_binaries, qwen_hiddenimports = collect_all("qwen_asr")
project_root = Path(SPECPATH)
local_binaries = [
    (str(path), "bin")
    for path in (
        project_root / "bin" / "ffmpeg.exe",
        project_root / "bin" / "ffprobe.exe",
        project_root / "bin" / "PuriPulyHeartGpuWorker.exe",
    )
    if path.is_file()
]

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=qwen_binaries + local_binaries,
    datas=qwen_datas,
    hiddenimports=qwen_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["vllm", "flash_attn"],
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
    name="QwenScribeDesktop",
)
