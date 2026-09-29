from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.config_service import ConfigService
from src.main_window import MainWindow


def test_linux_gal_cpu_opens_cutter_without_stt_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENSCRIBE_BUILD_VARIANT", "gal_cpu")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        config_service=ConfigService(tmp_path / "config.json"),
        model_service=None,
        active_backend="gal_cpu",
        supported_backends=frozenset(),
    )
    assert window.mode_stack.currentIndex() == 1
    assert window.gal_page.device == "cpu"
    assert not window.gal_page.qa.isEnabled()
    assert not window.mode_combo.isEnabled()
    assert not hasattr(window, "_worker_thread")
    window.close()
    app.processEvents()
