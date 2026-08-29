from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.config_service import ConfigService
from src.main_window import MainWindow
from src.transcription_worker import TranscriptionWorker


class _FakeModelService:
    device_index = 0
    model_available = True

    @staticmethod
    def gpu_information() -> tuple[bool, str]:
        return True, "CUDA cuda:0: Test GPU"

    @staticmethod
    def close() -> None:
        return None


def test_main_window_switches_between_chinese_and_english(
    tmp_path: Path, monkeypatch: object
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        TranscriptionWorker, "discover_devices", lambda self: None
    )
    config = ConfigService(tmp_path / "config.json")
    window = MainWindow(
        config_service=config,
        model_service=_FakeModelService(),
        active_backend="transformers",
        cuda_devices=[("cuda:0", "CUDA cuda:0: Test GPU")],
    )
    english_index = window.ui_language_combo.findData("en_US")
    window.ui_language_combo.setCurrentIndex(english_index)
    app.processEvents()

    assert window.start_button.text() == "Start transcription queue"
    assert window.drop_area.findChildren(type(window.start_button))[0].text() in {
        "Choose files",
        "Choose folder",
    }
    assert window.language_combo.itemText(0) == "Auto detect"
    assert config.get("ui_language") == "en_US"

    chinese_index = window.ui_language_combo.findData("zh_CN")
    window.ui_language_combo.setCurrentIndex(chinese_index)
    app.processEvents()
    assert window.start_button.text() == "开始转写队列"
    assert window.language_combo.itemText(0) == "自动识别"
    window.close()
    app.processEvents()


def test_vulkan_sku_hides_transformers_controls(tmp_path: Path, monkeypatch: object) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        TranscriptionWorker, "discover_devices", lambda self: None
    )
    config = ConfigService(tmp_path / "config.json")
    window = MainWindow(
        config_service=config,
        model_service=_FakeModelService(),
        active_backend="vulkan",
        supported_backends=frozenset({"vulkan"}),
        vulkan_devices=[("vulkan-index-1", "Vulkan: Test GPU")],
    )

    assert window.backend_combo.count() == 1
    assert window.backend_combo.currentData() == "vulkan"
    assert window.model_combo.count() == 1
    assert window.model_combo.currentData() == "vulkan"
    window.close()
    app.processEvents()
