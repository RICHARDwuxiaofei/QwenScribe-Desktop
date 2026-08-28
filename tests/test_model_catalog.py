from __future__ import annotations

from pathlib import Path

import pytest

import src.model_catalog as model_catalog
from src.model_catalog import (
    VULKAN_FILENAME,
    find_installed_model,
    is_complete_model,
)


def test_vulkan_model_requires_exact_file_size(tmp_path: Path) -> None:
    model = tmp_path / VULKAN_FILENAME
    model.write_bytes(b"not-a-model")
    assert not is_complete_model("vulkan", model)


def test_application_model_is_preferred_over_user_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_catalog, "VULKAN_SIZE", 4)
    local = tmp_path / "models" / VULKAN_FILENAME
    local.parent.mkdir()
    local.write_bytes(b"GGUF")
    assert find_installed_model("vulkan", tmp_path) == local
