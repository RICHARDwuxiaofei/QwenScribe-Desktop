"""Local model locations and download metadata.

Model weights deliberately live outside the packaged application.  Source
checkouts may keep a ``models`` folder beside ``app.py``; packaged builds use
the per-user data directory so an extracted application stays read-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from platformdirs import user_data_path


BackendName = Literal["transformers", "vulkan"]
DownloadRegion = Literal["china", "international"]

TRANSFORMERS_MODEL_ID = "Qwen/Qwen3-ASR-1.7B"
TRANSFORMERS_REVISION = "7278e1e70fe206f11671096ffdd38061171dd6e5"
VULKAN_REPO_ID = "handy-computer/Qwen3-ASR-1.7B-gguf"
VULKAN_REVISION = "92282af1610a2db19d66f2bef1e260f5deca782d"
VULKAN_FILENAME = "Qwen3-ASR-1.7B-Q6_K.gguf"
VULKAN_SIZE = 1_692_554_208
VULKAN_SHA256 = "c75a961b7134a6c952d89797865cb0d0376876185aee04ef6d12c31c2952e4e1"


@dataclass(frozen=True, slots=True)
class ModelFile:
    relative_path: str
    size_bytes: int
    sha256: str | None = None


TRANSFORMERS_FILES = (
    ModelFile("chat_template.json", 1_161),
    ModelFile("config.json", 6_194),
    ModelFile("configuration.json", 56),
    ModelFile("generation_config.json", 142),
    ModelFile("merges.txt", 1_671_853),
    ModelFile(
        "model-00001-of-00002.safetensors",
        4_220_320_824,
        "a4cd1f1a04d90b757dc7f7dd26254e69a013b19e80efe590a83c6a3bde8608d6",
    ),
    ModelFile(
        "model-00002-of-00002.safetensors",
        478_200_688,
        "6e0b9d9e09e2e0238e7ef3cc8a484ab387e91b90f1900bedf88bc92d7929ccfc",
    ),
    ModelFile("model.safetensors.index.json", 64_821),
    ModelFile("preprocessor_config.json", 330),
    ModelFile("tokenizer_config.json", 12_487),
    ModelFile("vocab.json", 2_776_833),
)


def user_models_directory() -> Path:
    return user_data_path("QwenASRDesktop", appauthor=False) / "models"


def download_target(backend: BackendName) -> Path:
    root = user_models_directory()
    if backend == "transformers":
        return root / "Qwen3-ASR-1.7B"
    return root / VULKAN_FILENAME


def model_candidates(backend: BackendName, application_directory: Path) -> tuple[Path, ...]:
    application_directory = Path(application_directory)
    if backend == "transformers":
        configured = os.environ.get("QWEN_ASR_MODEL_PATH", "").strip()
        local_name = "Qwen3-ASR-1.7B"
    else:
        configured = os.environ.get("QWEN_ASR_VULKAN_MODEL_PATH", "").strip()
        local_name = VULKAN_FILENAME
    values = [
        Path(configured).expanduser() if configured else None,
        application_directory / "models" / local_name,
        Path(os.environ.get("QWEN_ASR_PORTABLE_ROOT", "")) / "models" / local_name
        if os.environ.get("QWEN_ASR_PORTABLE_ROOT", "").strip()
        else None,
        download_target(backend),
    ]
    result: list[Path] = []
    for value in values:
        if value is not None and value not in result:
            result.append(value)
    return tuple(result)


def is_complete_model(backend: BackendName, path: Path) -> bool:
    if backend == "vulkan":
        return path.is_file() and path.stat().st_size == VULKAN_SIZE
    if not path.is_dir():
        return False
    # Accept a complete manually supplied official snapshot even if a future
    # revision changes JSON byte sizes.  Files downloaded by this application
    # are checked against the pinned catalog in ModelDownloadService.
    required = (
        "config.json",
        "model.safetensors.index.json",
        "preprocessor_config.json",
        "tokenizer_config.json",
        "vocab.json",
    )
    weights = tuple(path.glob("*.safetensors"))
    return bool(weights) and all(
        (path / name).is_file() and (path / name).stat().st_size > 0
        for name in required
    ) and all(weight.stat().st_size > 0 for weight in weights)


def find_installed_model(backend: BackendName, application_directory: Path) -> Path | None:
    return next(
        (
            candidate
            for candidate in model_candidates(backend, application_directory)
            if is_complete_model(backend, candidate)
        ),
        None,
    )
