"""Bounded diagnostics for packaged QwenScribe runtimes.

Package smoke deliberately checks only the files and build capabilities that
are part of a release. Native Vulkan enumeration is exposed separately by
the worker's ``--diagnose-vulkan`` command so CI does not require a GPU.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .build_config import application_directory, choose_supported_backend, current_build


def _phase(report: dict[str, Any], name: str, **details: Any) -> None:
    phases = report.setdefault("phases", [])
    assert isinstance(phases, list)
    phases.append({"name": name, "timestamp": time.time(), **details})


def _write(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _base_report() -> tuple[dict[str, Any], Path, str, bool]:
    build = current_build()
    backend, warning = choose_supported_backend(None, build)
    root = application_directory()
    return (
        {
            "schema_version": 1,
            "ok": False,
            "build_variant": build.variant,
            "default_backend": backend,
            "unsupported_warning": warning,
            "resource_directory": str(root),
            "included_backends": sorted(build.backends),
            "worker_path": None,
            "vulkan": None,
            "phases": [],
        },
        root,
        backend,
        warning,
    )


def run_package(output: Path) -> int:
    """Check a frozen package without loading Qt or touching a GPU."""
    report, root, backend, warning = _base_report()
    _phase(report, "startup")
    try:
        _phase(report, "resolve_resource_directory", path=str(root))
        if warning:
            raise RuntimeError("fresh package selected an unsupported backend")
        suffix = ".exe" if os.name == "nt" else ""
        if backend == "vulkan":
            worker = root / "bin" / f"PuriPulyHeartGpuWorker{suffix}"
            report["worker_path"] = str(worker)
            if not worker.is_file():
                raise FileNotFoundError(f"Vulkan worker is missing: {worker}")
        elif backend not in ("transformers", "gal_cpu"):
            raise RuntimeError(f"unsupported package backend: {backend}")

        if backend != "gal_cpu":
            ffmpeg = root / "bin" / f"ffmpeg{suffix}"
            ffprobe = root / "bin" / f"ffprobe{suffix}"
            report["ffmpeg_path"] = str(ffmpeg)
            report["ffprobe_path"] = str(ffprobe)
            if not ffmpeg.is_file() or not ffprobe.is_file():
                raise FileNotFoundError("packaged FFmpeg/FFprobe is missing")
        if backend in ("transformers", "gal_cpu") and (root / "bin" / f"PuriPulyHeartGpuWorker{suffix}").exists():
            raise RuntimeError("CUDA package contains the Vulkan worker")
        _phase(report, "package_validation", backend=backend)
        report["ok"] = True
        return 0
    except Exception as error:
        report["error_code"] = "package_boundary"
        report["error_message"] = str(error)
        raise
    finally:
        _phase(report, "report_written")
        _write(report, output)
        _phase(report, "exit", ok=bool(report.get("ok")))
        _write(report, output)


def run_hardware(output: Path) -> int:
    """Run the real Python-to-worker discovery path with durable phase output."""
    from .vulkan_model_service import VulkanModelService

    report, root, backend, warning = _base_report()
    service: VulkanModelService | None = None

    def save_phase(name: str, **details: Any) -> None:
        _phase(report, name, **details)
        _write(report, output)

    save_phase("startup")
    try:
        save_phase("resolve_resource_directory", path=str(root))
        if warning:
            raise RuntimeError("fresh package selected an unsupported backend")
        if backend != "vulkan":
            report["ok"] = True
            return 0

        save_phase("create_vulkan_service")
        service = VulkanModelService(root, device_id="auto")
        save_phase("worker_start")
        service._ensure_worker()
        save_phase("worker_authenticated")
        save_phase("discover_request_sent")
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
        save_phase("discover_response", ok=result.ok)
        if not result.ok:
            report["error_code"] = result.error_code
            report["error_message"] = result.error_message
            return 3
        report["ok"] = True
        return 0
    except Exception as error:
        report["error_code"] = getattr(error, "code", "discovery_exception")
        report["error_message"] = str(error)
        raise
    finally:
        save_phase("worker_dispose")
        if service is not None:
            service._dispose_worker()
        save_phase("report_written")
        _phase(report, "exit", ok=bool(report.get("ok")))
        _write(report, output)


def run(output: Path) -> int:
    """Backward-compatible alias: ``--smoke-test`` is package smoke."""
    return run_package(output)
