"""QwenASRDesktop executable entry point."""

from __future__ import annotations

import logging
import faulthandler
import os
import sys
import traceback
from pathlib import Path
from typing import IO

from PySide6.QtWidgets import QApplication, QMessageBox

from src.logging_service import configure_logging
from src.main_window import MainWindow
from src.config_service import ConfigService
from src.model_service import ModelService
from src.utils import cleanup_stale_temp_directories
from src.vulkan_model_service import VulkanModelService


_NATIVE_CRASH_STREAM: IO[str] | None = None


def _enable_native_crash_logging(log_path: Path) -> None:
    """Keep a dedicated stream open so faulthandler can record native crashes."""
    global _NATIVE_CRASH_STREAM
    crash_path = log_path.with_name("QwenASRDesktop-native-crash.log")
    _NATIVE_CRASH_STREAM = crash_path.open("a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=_NATIVE_CRASH_STREAM, all_threads=True)


def main() -> int:
    if "--transformers-worker" in sys.argv:
        # PyInstaller onedir reuses this executable for the isolated CUDA worker.
        from src.transformers_worker import main as worker_main

        return worker_main()

    log_path = configure_logging()
    _enable_native_crash_logging(log_path)
    logger = logging.getLogger(__name__)
    removed = cleanup_stale_temp_directories()
    if removed:
        logger.info("启动时清理了 %d 个超过 24 小时的临时目录", removed)

    application = QApplication(sys.argv)
    application.setApplicationName("QwenASRDesktop")
    application.setOrganizationName("QwenASRDesktop")

    application_directory = Path(
        getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    )
    os.environ.setdefault("QWEN_ASR_PORTABLE_ROOT", str(Path(sys.executable).resolve().parent))
    config = ConfigService()
    backend = str(config.get("inference_backend", "transformers"))
    if backend not in {"transformers", "vulkan"}:
        backend = "transformers"

    if backend == "vulkan":
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
        cuda_devices=[],
        vulkan_devices=[],
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
