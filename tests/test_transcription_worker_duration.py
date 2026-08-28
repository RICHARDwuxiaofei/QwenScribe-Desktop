from __future__ import annotations

from io import StringIO
from pathlib import Path
import threading

from src.media_service import MediaInfo
from src.model_service import TranscriptionResult
from src.transcription_worker import TranscriptionTask, TranscriptionWorker


class _FakeModelService:
    is_loaded = True

    def transcribe(self, _chunk_path: Path, _language: str | None) -> TranscriptionResult:
        return TranscriptionResult(text="测试", language="Chinese")

    @staticmethod
    def is_out_of_memory(_error: BaseException) -> bool:
        return False


class _EstimatedAacMediaService:
    """Simulate a raw AAC whose bitrate-based duration is badly overestimated."""

    def __init__(self) -> None:
        self.probe_count = 0
        self.detect_duration: float | None = None
        self.created_ranges: list[tuple[float, float]] = []

    def probe(self, _path: Path, _cancel_event: threading.Event) -> MediaInfo:
        self.probe_count += 1
        if self.probe_count == 1:
            return MediaInfo(duration=7707.189, audio_stream_count=1)
        return MediaInfo(duration=500.0, audio_stream_count=1)

    def extract_audio(
        self,
        _input_path: Path,
        output_path: Path,
        _duration: float,
        _cancel_event: threading.Event,
        progress_callback: object,
    ) -> None:
        output_path.touch()

    def detect_silence(
        self,
        _audio_path: Path,
        duration: float,
        _cancel_event: threading.Event,
        progress_callback: object,
    ) -> list[tuple[float, float]]:
        self.detect_duration = duration
        return []

    def create_chunk(
        self,
        _audio_path: Path,
        _output_path: Path,
        start: float,
        duration: float,
        _cancel_event: threading.Event,
    ) -> None:
        self.created_ranges.append((start, start + duration))


def test_extracted_audio_duration_is_used_for_chunk_boundaries(tmp_path: Path) -> None:
    model_service = _FakeModelService()
    media_service = _EstimatedAacMediaService()
    worker = TranscriptionWorker(tmp_path, model_service=model_service)  # type: ignore[arg-type]
    worker._media_service = media_service  # type: ignore[assignment]
    worker._full_audio_path = tmp_path / "source.wav"
    worker._task_temp_directory = tmp_path
    worker._partial_handle = StringIO()

    worker._execute_task(
        TranscriptionTask(
            input_path=tmp_path / "estimated-duration.aac",
            output_directory=tmp_path,
            language=None,
        )
    )

    assert media_service.probe_count == 2
    assert media_service.detect_duration == 500.0
    assert media_service.created_ranges
    assert media_service.created_ranges[-1][1] == 500.0
    assert all(end <= 500.0 for _start, end in media_service.created_ranges)
