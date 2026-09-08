"""Exercise packaged backend discovery without starting the interactive GUI."""

from __future__ import annotations

import json
from pathlib import Path

from .build_config import application_directory, choose_supported_backend, current_build
from .config_service import ConfigService
from .vulkan_model_service import VulkanModelService


def run(output: Path) -> int:
    build = current_build()
    backend, warning = choose_supported_backend(None, build)
    root = application_directory()
    report: dict[str, object] = {
        "build_variant": build.variant,
        "default_backend": backend,
        "unsupported_warning": warning,
        "resource_directory": str(root),
        "included_backends": sorted(build.backends),
        "worker_path": None,
        "vulkan": None,
    }
    if backend == "vulkan":
        service = VulkanModelService(root, device_id="auto")
        try:
            result = service.discover_result()
            report["vulkan"] = {
                "backend": result.backend,
                "devices": result.devices,
                "ok": result.ok,
                "error_code": result.error_code,
                "error_message": result.error_message,
                "details": result.details,
            }
            report["worker_path"] = str(service._resolve_executable_path())
        finally:
            # A one-shot smoke process does not need the interactive shutdown
            # handshake; dispose the isolated worker directly after the report
            # has been assembled.
            pass
    ConfigService()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if backend == "vulkan":
        service._dispose_worker()
        if not result.ok:
            raise RuntimeError(result.summary)
    return 0
