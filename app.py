"""QwenASRDesktop executable entry point."""

from __future__ import annotations

import logging
import faulthandler
import json
import os
import sys
import traceback
from pathlib import Path
from typing import IO

from src.build_config import (
    application_directory as resource_directory,
    choose_supported_backend,
    current_build,
    diagnostic,
    unsupported_backend_message,
)


_NATIVE_CRASH_STREAM: IO[str] | None = None


def _prepare_frozen_dll_search_path(application_directory: Path) -> None:
    """Make nested PySide6 and shiboken6 DLLs loadable on Windows onedir builds."""
    if os.name != "nt":
        return
    candidates = (
        application_directory,
        application_directory / "PySide6",
        application_directory / "shiboken6",
    )
    for directory in candidates:
        if directory.is_dir():
            try:
                os.add_dll_directory(str(directory.resolve()))
            except OSError:
                # Python versions without AddDllDirectory support still use PATH
                # from the bootloader; importing Qt should remain the fallback.
                pass


def _enable_native_crash_logging(log_path: Path) -> None:
    """Keep a dedicated stream open so faulthandler can record native crashes."""
    global _NATIVE_CRASH_STREAM
    crash_path = log_path.with_name("QwenASRDesktop-native-crash.log")
    _NATIVE_CRASH_STREAM = crash_path.open("a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=_NATIVE_CRASH_STREAM, all_threads=True)


def main() -> int:
    if "--gal-cutter-cli" in sys.argv:
        from src.gal_cutter_cli import main as gal_cli_main

        return gal_cli_main(sys.argv[sys.argv.index("--gal-cutter-cli") + 1:])
    if "--forced-aligner-worker" in sys.argv:
        from src.forced_aligner_worker import main as worker_main

        return worker_main()
    if "--transformers-worker" in sys.argv:
        # PyInstaller onedir reuses this executable for the isolated CUDA worker.
        from src.transformers_worker import main as worker_main

        return worker_main()

    application_directory = resource_directory()
    _prepare_frozen_dll_search_path(application_directory)
    if "--smoke-test-package" in sys.argv or "--smoke-test" in sys.argv:
        from src.runtime_smoke import run_package

        option = "--smoke-test-package" if "--smoke-test-package" in sys.argv else "--smoke-test"
        return run_package(Path(sys.argv[sys.argv.index(option) + 1]))
    if "--smoke-test-hardware" in sys.argv:
        from src.runtime_smoke import run_hardware

        return run_hardware(Path(sys.argv[sys.argv.index("--smoke-test-hardware") + 1]))
    check_requested = "--check" in sys.argv or os.environ.get("QWENSCRIBE_RUN_CHECK") == "1"
    if check_requested:
        report = json.dumps(diagnostic(application_directory), ensure_ascii=False, sort_keys=True)
        check_output = os.environ.get("QWENSCRIBE_CHECK_OUTPUT", "").strip()
        if "--check-output" in sys.argv:
            output_index = sys.argv.index("--check-output") + 1
            if output_index >= len(sys.argv):
                raise SystemExit("--check-output requires a file path")
            check_output = sys.argv[output_index]
        if check_output:
            Path(check_output).write_text(report + "\n", encoding="utf-8")
        print(report)
        return 0

    # Keep GUI, media and backend imports after --check.  This makes the
    # packaged diagnostic useful on a clean machine even when GUI startup or
    # optional native runtimes are the thing being diagnosed.
    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.config_service import ConfigService
    from src.logging_service import configure_logging
    from src.main_window import MainWindow
    from src.model_service import ModelService
    from src.utils import cleanup_stale_temp_directories
    from src.vulkan_model_service import VulkanModelService

    log_path = configure_logging()
    _enable_native_crash_logging(log_path)
    logger = logging.getLogger(__name__)
    removed = cleanup_stale_temp_directories()
    if removed:
        logger.info("启动时清理了 %d 个超过 24 小时的临时目录", removed)

    application = QApplication(sys.argv)
    application.setApplicationName("QwenASRDesktop")
    application.setOrganizationName("QwenASRDesktop")

    os.environ.setdefault("QWEN_ASR_PORTABLE_ROOT", str(Path(sys.executable).resolve().parent))
    config = ConfigService()
    capabilities = current_build()
    backend = str(config.get("inference_backend")) if "inference_backend" in config.data else None
    requested_backend = backend
    backend, unsupported_backend = choose_supported_backend(backend, capabilities)
    if unsupported_backend:
        logger.warning(unsupported_backend_message(requested_backend, capabilities))

    if backend == "gal_cpu":
        model_service = None
    elif backend == "vulkan":
        selected_device = str(config.get("vulkan_device_id", "auto")).strip() or "auto"
        model_service = VulkanModelService(
            application_directory,
            device_id=selected_device,
        )
    else:
        selected_cuda = str(config.get("cuda_device_id", "cuda:0"))
        try:
            cuda_index = int(selected_cuda.removeprefix("cuda:"))
        except ValueError:
            cuda_index = 0
            selected_cuda = "cuda:0"
        model_service = ModelService(
            application_directory=application_directory,
            device_index=cuda_index,
        )

    def handle_uncaught(exception_type: type[BaseException], value: BaseException, tb: object) -> None:
        logger.critical(
            "未捕获异常\n%s", "".join(traceback.format_exception(exception_type, value, tb))
        )
        QMessageBox.critical(
            None,
            "QwenASRDesktop 发生错误",
            f"发生未处理错误：{value}\n\n完整信息已写入：\n{log_path}",
        )

    sys.excepthook = handle_uncaught
    window = MainWindow(
        config_service=config,
        model_service=model_service,
        active_backend=backend,
        supported_backends=capabilities.backends,
        unsupported_backend_message=(
            unsupported_backend_message(requested_backend, capabilities)
            if unsupported_backend
            else None
        ),
        cuda_devices=[],
        vulkan_devices=[],
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
