"""Load the configured ASR model inside a Qt worker thread and exit."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.model_service import ModelService  # noqa: E402


class Loader(QObject):
    finished = Signal(int)

    def __init__(self, audio_path: Path | None = None) -> None:
        super().__init__()
        self._audio_path = audio_path

    @Slot()
    def run(self) -> None:
        try:
            service = ModelService()
            available, description = service.gpu_information()
            if not available:
                raise RuntimeError(description)
            print(f"Qt worker GPU probe OK: {description}", flush=True)
            service.load()
            print("Qt worker model load OK", flush=True)
            if self._audio_path is not None:
                result = service.transcribe(self._audio_path, None)
                print(
                    f"Qt worker transcription OK: chars={len(result.text)}, "
                    f"language={result.language or 'unknown'}",
                    flush=True,
                )
            self.finished.emit(0)
        except Exception:
            traceback.print_exc()
            self.finished.emit(1)


def main() -> int:
    local_model = PROJECT_ROOT / "models" / "Qwen3-ASR-1.7B"
    os.environ.setdefault("QWEN_ASR_MODEL_PATH", str(local_model))

    application = QCoreApplication([])
    thread = QThread()
    thread.setStackSize(64 * 1024 * 1024)
    audio_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    loader = Loader(audio_path)
    loader.moveToThread(thread)
    thread.started.connect(loader.run)
    loader.finished.connect(application.exit)
    thread.start()
    exit_code = application.exec()
    thread.quit()
    thread.wait()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
