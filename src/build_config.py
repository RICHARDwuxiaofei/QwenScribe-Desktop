"""Declared capabilities for QwenScribe release variants.

PyInstaller runtime hooks set ``QWENSCRIBE_BUILD_VARIANT`` in packaged builds.
Source runs default to ``full`` for backward compatibility; a release never
guesses its feature set from the machine it happens to run on.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


BUILD_VARIANTS = frozenset({"full", "vulkan", "cuda", "gal_cpu"})


@dataclass(frozen=True, slots=True)
class BuildCapabilities:
    variant: str
    backends: frozenset[str]

    @property
    def has_vulkan_backend(self) -> bool:
        return "vulkan" in self.backends

    @property
    def has_transformers_backend(self) -> bool:
        return "transformers" in self.backends


def current_build() -> BuildCapabilities:
    requested = os.environ.get("QWENSCRIBE_BUILD_VARIANT", "full").strip().lower()
    variant = requested if requested in BUILD_VARIANTS else "full"
    backends = {
        "full": frozenset({"transformers", "vulkan"}),
        "vulkan": frozenset({"vulkan"}),
        "cuda": frozenset({"transformers"}),
        "gal_cpu": frozenset(),
    }[variant]
    return BuildCapabilities(variant=variant, backends=backends)


def application_directory() -> Path:
    """Resolve bundled resources, not the directory containing the launcher."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)).resolve()


def choose_supported_backend(requested: str | None, capabilities: BuildCapabilities | None = None) -> tuple[str, bool]:
    """Return the supported operational backend and flag an invalid preference."""
    capabilities = capabilities or current_build()
    if capabilities.variant == "gal_cpu":
        return "gal_cpu", requested not in (None, "gal_cpu")
    if requested is None:
        return ("transformers" if capabilities.has_transformers_backend else "vulkan"), False
    if requested in capabilities.backends:
        return requested, False
    # The caller must disclose this before using it.  This does not overwrite
    # configuration or substitute a GPU device.
    return ("vulkan" if capabilities.has_vulkan_backend else "transformers"), True


def unsupported_backend_message(requested: str, capabilities: BuildCapabilities | None = None) -> str:
    capabilities = capabilities or current_build()
    if capabilities.variant == "gal_cpu":
        return "当前发行版本仅支持 Gal TTS Cutter（CPU）；普通 STT 需要 Windows CUDA 或 Vulkan 发行版。"
    labels = {"transformers": "CUDA / Transformers", "vulkan": "Vulkan / GGUF"}
    available = "、".join(labels[item] for item in sorted(capabilities.backends))
    return (
        f"当前发行版本不包含 {labels.get(requested, requested)} 后端。"
        f"当前版本可用：{available}。请选择当前版本支持的后端，或下载另一个发行版本。"
    )


def diagnostic(application_directory: Path) -> dict[str, object]:
    """Return a JSON-safe package diagnostic without importing heavy backends."""
    capabilities = current_build()
    application_directory = Path(application_directory).resolve()
    executable_suffix = ".exe" if os.name == "nt" else ""
    worker = application_directory / "bin" / f"PuriPulyHeartGpuWorker{executable_suffix}"
    ffmpeg = application_directory / "bin" / f"ffmpeg{executable_suffix}"
    ffprobe = application_directory / "bin" / f"ffprobe{executable_suffix}"
    return {
        "application_directory": str(application_directory),
        "build_variant": capabilities.variant,
        "included_backends": sorted(capabilities.backends),
        "frozen": bool(getattr(sys, "frozen", False)),
        "ffmpeg": str(ffmpeg) if ffmpeg.is_file() else None,
        "ffprobe": str(ffprobe) if ffprobe.is_file() else None,
        "vulkan_worker": str(worker) if worker.is_file() else None,
        "portable_root": str(Path(sys.executable).resolve().parent),
        "references_development_directory": not bool(getattr(sys, "frozen", False)),
    }
