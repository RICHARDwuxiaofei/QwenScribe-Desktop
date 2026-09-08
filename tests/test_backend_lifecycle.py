import io
from types import SimpleNamespace

import pytest

from src.exceptions import ModelLoadError
from src.model_service import ModelService
from src.vulkan_model_service import VulkanModelService, VulkanWorkerError


def test_transformers_dead_process_is_not_loaded(tmp_path):
    service = ModelService(application_directory=tmp_path)
    service._loaded = True
    service._process = SimpleNamespace(poll=lambda: 1)
    assert not service.is_loaded


def test_transformers_missing_model_does_not_start_remote_download(tmp_path, monkeypatch):
    service = ModelService(application_directory=tmp_path)
    monkeypatch.setattr("src.model_service.find_installed_model", lambda *args: None)
    calls = []
    monkeypatch.setattr(service, "_request", lambda *args, **kwargs: calls.append(args) or {})
    with pytest.raises(ModelLoadError):
        service.load()
    assert calls == []


def test_vulkan_dead_process_is_not_loaded(tmp_path):
    service = VulkanModelService(tmp_path, device_id="auto")
    service._loaded = True
    service._process = SimpleNamespace(poll=lambda: 1)
    assert not service.is_loaded


def test_vulkan_heartbeats_do_not_extend_request_deadline(tmp_path, monkeypatch):
    service = VulkanModelService(tmp_path, device_id="auto")
    monkeypatch.setattr(service, "_ensure_worker", lambda: None)
    service._connection = SimpleNamespace(settimeout=lambda timeout: None, close=lambda: None)
    service._stream = io.BytesIO()
    ticks = iter([0.0, 0.0, 0.6, 1.2, 2.0])
    monkeypatch.setattr("src.vulkan_model_service.time", SimpleNamespace(monotonic=lambda: next(ticks)), raising=False)
    reads = []

    def read_frame():
        reads.append(True)
        if len(reads) > 3:
            raise AssertionError("heartbeat kept request alive beyond deadline")
        return {"type": "heartbeat"}

    monkeypatch.setattr(service, "_read_frame", read_frame)
    with pytest.raises(TimeoutError):
        service._request("discover", timeout=1.0)
    assert len(reads) <= 2


def test_vulkan_broken_transport_invalidates_loaded_model(tmp_path, monkeypatch):
    service = VulkanModelService(tmp_path, device_id="auto")
    monkeypatch.setattr(service, "_ensure_worker", lambda: None)
    service._connection = SimpleNamespace(settimeout=lambda timeout: None, close=lambda: None)
    service._stream = io.BytesIO()
    service._loaded = True
    with pytest.raises(VulkanWorkerError, match="worker_closed"):
        service._request("transcribe", timeout=1.0)
    assert not service._loaded
    assert service._stream is None


def test_vulkan_frame_read_is_bounded(tmp_path):
    service = VulkanModelService(tmp_path, device_id="auto")

    class Stream:
        def readline(self, size=-1):
            assert 0 < size <= 4 * 1024 * 1024 + 1
            return b"x" * size

    service._stream = Stream()
    with pytest.raises(VulkanWorkerError, match="frame_too_large"):
        service._read_frame()


def test_vulkan_cleanup_during_request_does_not_reenter_request_lock(tmp_path, monkeypatch):
    service = VulkanModelService(tmp_path, device_id="auto")
    service._process = SimpleNamespace(poll=lambda: None, wait=lambda **kwargs: None)
    service._stream = None  # worker started but transport is not established
    service._connection = SimpleNamespace(close=lambda: None)
    # Cleanup must never send a request that tries to acquire this held lock.
    with service._request_lock:
        service.close()
    assert service._process is None
