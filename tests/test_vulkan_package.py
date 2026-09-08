import json

from scripts.check_vulkan_package import forbidden_vulkan_files


def test_rejects_loader_layers_and_arbitrarily_named_icd(tmp_path):
    for name in ("VULKAN-1.DLL", "VkLayer_khronos_validation.dll"):
        (tmp_path / name).touch()
    (tmp_path / "driver.json").write_text(json.dumps({"file_format_version": "1.0.0", "ICD": {"library_path": "driver.dll"}}))
    (tmp_path / "app.json").write_text('{"name":"config"}')
    assert len(forbidden_vulkan_files(tmp_path)) == 3


def test_worker_is_allowed(tmp_path):
    (tmp_path / "PuriPulyHeartGpuWorker.exe").touch()
    assert forbidden_vulkan_files(tmp_path) == []
