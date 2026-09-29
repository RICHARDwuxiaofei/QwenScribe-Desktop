import json
import os
from pathlib import Path

import pytest

import src.runtime_smoke as runtime_smoke
import src.vulkan_model_service as vulkan_model_service


def _fake_package(tmp_path: Path, *, worker: bool = True) -> Path:
    root = tmp_path / "_internal"
    (root / "bin").mkdir(parents=True)
    suffix = ".exe" if os.name == "nt" else ""
    names = [f"ffmpeg{suffix}", f"ffprobe{suffix}"]
    if worker:
        names.append(f"PuriPulyHeartGpuWorker{suffix}")
    for name in names:
        (root / "bin" / name).write_bytes(b"test")
    return root


def test_package_smoke_does_not_start_vulkan_worker(tmp_path, monkeypatch):
    root = _fake_package(tmp_path)
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "vulkan")
    monkeypatch.setattr(runtime_smoke, "application_directory", lambda: root)

    output = tmp_path / "package-smoke.json"
    assert runtime_smoke.run_package(output) == 0
    assert "VulkanModelService" not in runtime_smoke.__dict__
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["default_backend"] == "vulkan"
    assert [phase["name"] for phase in report["phases"]][-1] == "exit"


def test_hardware_smoke_always_disposes_worker(tmp_path, monkeypatch):
    root = _fake_package(tmp_path)
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "vulkan")
    monkeypatch.setattr(runtime_smoke, "application_directory", lambda: root)
    disposed = []

    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        def _ensure_worker(self):
            return None

        def discover_result(self):
            raise RuntimeError("simulated discovery failure")

        def _dispose_worker(self):
            disposed.append(True)

        def _resolve_executable_path(self):
            return root / "bin" / f"PuriPulyHeartGpuWorker{'.exe' if os.name == 'nt' else ''}"

    monkeypatch.setattr(vulkan_model_service, "VulkanModelService", FakeService)
    output = tmp_path / "hardware-smoke.json"
    with pytest.raises(RuntimeError, match="simulated discovery failure"):
        runtime_smoke.run_hardware(output)
    assert disposed == [True]
    report = json.loads(output.read_text(encoding="utf-8"))
    names = [phase["name"] for phase in report["phases"]]
    assert "discover_request_sent" in names
    assert "worker_dispose" in names
    assert names[-1] == "exit"


def test_cuda_package_smoke_uses_transformers_without_vulkan_worker(tmp_path, monkeypatch):
    root = _fake_package(tmp_path, worker=False)
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "cuda")
    monkeypatch.setattr(runtime_smoke, "application_directory", lambda: root)
    output = tmp_path / "cuda-package-smoke.json"
    assert runtime_smoke.run_package(output) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["default_backend"] == "transformers"
    assert report["unsupported_warning"] is False


def test_linux_gal_cpu_package_needs_no_ffmpeg_or_vulkan_worker(tmp_path, monkeypatch):
    root = tmp_path / "_internal"
    root.mkdir()
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "gal_cpu")
    monkeypatch.setattr(runtime_smoke, "application_directory", lambda: root)
    output = tmp_path / "gal-smoke.json"
    assert runtime_smoke.run_package(output) == 0
    report = json.loads(output.read_text())
    assert report["default_backend"] == "gal_cpu"
    assert report["ok"]
