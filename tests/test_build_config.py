from __future__ import annotations

from pathlib import Path

from src.build_config import (
    choose_supported_backend,
    current_build,
    diagnostic,
    unsupported_backend_message,
)


def test_vulkan_variant_exposes_only_vulkan(monkeypatch: object) -> None:
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "vulkan")  # type: ignore[attr-defined]
    capabilities = current_build()

    assert capabilities.variant == "vulkan"
    assert capabilities.backends == frozenset({"vulkan"})
    assert choose_supported_backend("transformers", capabilities) == ("vulkan", True)
    assert "当前发行版本不包含" in unsupported_backend_message("transformers", capabilities)


def test_cuda_variant_exposes_only_transformers(monkeypatch: object) -> None:
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "cuda")  # type: ignore[attr-defined]
    capabilities = current_build()

    assert capabilities.variant == "cuda"
    assert capabilities.backends == frozenset({"transformers"})
    assert choose_supported_backend("vulkan", capabilities) == ("transformers", True)


def test_unknown_variant_defaults_to_full(monkeypatch: object) -> None:
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "not-a-release")  # type: ignore[attr-defined]

    assert current_build().variant == "full"


def test_diagnostic_reports_declared_capabilities(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "vulkan")  # type: ignore[attr-defined]
    report = diagnostic(tmp_path)

    assert report["build_variant"] == "vulkan"
    assert report["included_backends"] == ["vulkan"]
    assert report["ffmpeg"] is None
