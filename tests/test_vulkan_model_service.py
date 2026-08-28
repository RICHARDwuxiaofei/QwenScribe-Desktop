from __future__ import annotations

from pathlib import Path

import pytest

from src.vulkan_model_service import (
    VulkanDevice,
    VulkanModelService,
    VulkanWorkerError,
)


def _devices() -> tuple[VulkanDevice, ...]:
    return (
        VulkanDevice(
            device_id="0000:01:00.0",
            registry_index=0,
            name="Vulkan0",
            description="NVIDIA GeForce RTX 4070 SUPER",
            device_type="gpu",
            memory_total_bytes=12 * 1024**3,
            memory_free_bytes=10 * 1024**3,
        ),
        VulkanDevice(
            device_id="vulkan-index-1",
            registry_index=1,
            name="Vulkan1",
            description="Intel(R) UHD Graphics 770",
            device_type="igpu",
            memory_total_bytes=32 * 1024**3,
            memory_free_bytes=30 * 1024**3,
        ),
    )


def test_vulkan_device_label_uses_reported_description() -> None:
    assert "Intel(R) UHD Graphics 770" in _devices()[1].display_label
    assert "核显" in _devices()[1].display_label


def test_explicit_vulkan_device_selection_is_exact(tmp_path: Path) -> None:
    service = VulkanModelService(tmp_path, device_id="vulkan-index-1")
    assert service._select_device(_devices()).device_id == "vulkan-index-1"


def test_missing_explicit_vulkan_device_does_not_fallback(tmp_path: Path) -> None:
    service = VulkanModelService(tmp_path, device_id="missing-device")
    with pytest.raises(VulkanWorkerError, match="device_unavailable"):
        service._select_device(_devices())


def test_vulkan_oom_is_detected_without_importing_torch(tmp_path: Path) -> None:
    service = VulkanModelService(tmp_path, device_id="vulkan-index-1")
    assert service.is_out_of_memory(VulkanWorkerError("out_of_memory"))
    assert not service.is_out_of_memory(VulkanWorkerError("decode_failure"))
