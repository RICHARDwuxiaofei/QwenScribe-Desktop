from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.build_config import application_directory, choose_supported_backend, current_build
from src.device_discovery import DiscoveryResult
from src.transcription_worker import TranscriptionWorker
from src.vulkan_model_service import VulkanModelService, VulkanWorkerError


@pytest.mark.parametrize("variant,expected", [("vulkan", "vulkan"), ("cuda", "transformers"), ("full", "transformers")])
def test_fresh_sku_default_does_not_warn(monkeypatch, variant, expected):
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", variant)
    assert choose_supported_backend(None, current_build()) == (expected, False)


@pytest.mark.parametrize("variant,saved,expected", [("vulkan", "transformers", "vulkan"), ("cuda", "vulkan", "transformers"), ("vulkan", "invalid", "vulkan")])
def test_saved_unsupported_backend_warns(monkeypatch, variant, saved, expected):
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", variant)
    assert choose_supported_backend(saved) == (expected, True)


def test_frozen_resource_directory_is_internal(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "QwenScribeDesktop.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    assert application_directory() == tmp_path / "_internal"


def service_with_payload(tmp_path, monkeypatch, payload):
    service = VulkanModelService(tmp_path, device_id="stale-old-gpu")
    monkeypatch.setattr(service, "_ensure_worker", lambda: None)
    monkeypatch.setattr(service, "_request", lambda *a, **k: payload)
    return service


def test_discovery_success_ignores_stale_id(tmp_path, monkeypatch):
    payload = {"devices": [{"device_id": "reported-id", "registry_index": 0,
                           "name": "Vulkan0", "description": "Reported integrated GPU", "device_type": "igpu"}]}
    service = service_with_payload(tmp_path, monkeypatch, payload)
    result = service.discover_result()
    assert result.ok and result.devices[0][0] == "reported-id"
    assert "核显" in result.devices[0][1]
    with pytest.raises(VulkanWorkerError, match="device_unavailable"):
        service._select_device(service.discover_devices())


def test_empty_is_successful_enumeration(tmp_path, monkeypatch):
    result = service_with_payload(tmp_path, monkeypatch, {"devices": []}).discover_result()
    assert result.ok and result.devices == () and result.error_code is None
    assert "未发现设备" in result.summary


@pytest.mark.parametrize("code", ["backend_unavailable", "backend_initialization_failed", "device_index_missing"])
def test_backend_diagnostics_propagate(tmp_path, monkeypatch, code):
    diagnostic = {"all_devices": [], "error": {"code": code, "message": "native error"}}
    result = service_with_payload(tmp_path, monkeypatch, {"devices": [], "diagnostic": diagnostic}).discover_result()
    assert not result.ok and result.error_code == code
    assert result.details["error"]["message"] == "native error"


@pytest.mark.parametrize("error,code", [(VulkanWorkerError("worker_startup_failed", {"exit_code": 42}), "worker_startup_failed"), (VulkanWorkerError("protocol_invalid"), "protocol_invalid"), (RuntimeError("unexpected"), "discovery_exception")])
def test_discovery_exceptions_reach_signal(tmp_path, monkeypatch, error, code):
    def fail(self):
        raise error
    monkeypatch.setattr(VulkanModelService, "discover_devices", fail)
    worker = TranscriptionWorker(tmp_path, model_service=object(), supported_backends=frozenset({"vulkan"}))
    reports = []
    worker.devices_discovered.connect(lambda cuda, vulkan: reports.append((cuda, vulkan)))
    worker.discover_devices()
    cuda, report = reports[0]
    assert cuda == [] and not report.ok and report.error_code == code
    assert asdict(report)["details"]["exception"]


def test_missing_worker_has_specific_error(tmp_path, monkeypatch):
    monkeypatch.delenv("QWEN_ASR_VULKAN_WORKER_PATH", raising=False)
    result = VulkanModelService(tmp_path, device_id="auto").discover_result()
    assert result.error_code == "worker_missing"
    assert result.details["path"] == str(tmp_path / "bin" / "PuriPulyHeartGpuWorker.exe")


def test_cuda_sku_never_constructs_vulkan_worker(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setattr(VulkanModelService, "__init__", lambda *a, **k: pytest.fail("Vulkan imported by CUDA SKU"))
    worker = TranscriptionWorker(tmp_path, model_service=object(), supported_backends=frozenset({"transformers"}))
    reports = []
    worker.devices_discovered.connect(lambda c, v: reports.append(v))
    worker.discover_devices()
    assert reports[0].error_code == "not_included"
