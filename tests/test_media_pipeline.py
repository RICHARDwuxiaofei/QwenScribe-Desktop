from pathlib import Path
import wave

import pytest

from src.exceptions import FFmpegNotFoundError
from src.media_service import MediaService
from src.model_service import TranscriptionResult
from src.transcription_worker import TranscriptionTask, TranscriptionWorker


def test_real_ffmpeg_stereo_silence_to_partial_and_final_text(tmp_path):
    root = Path(__file__).resolve().parents[1]
    try:
        media = MediaService(root)
    except FFmpegNotFoundError:
        pytest.skip("FFmpeg/FFprobe not installed")
    source = tmp_path / "stereo.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0" * 44100 * 2 * 2)

    class Model:
        is_loaded = True
        chunk_suffix = ".wav"
        calls = 0

        def transcribe(self, path, language):
            with wave.open(str(path), "rb") as chunk:
                assert chunk.getnchannels() == 1
                assert chunk.getframerate() == 16000
                assert chunk.getsampwidth() == 2
                assert chunk.getnframes() == 16000
            self.calls += 1
            return TranscriptionResult("pipeline sentinel", None)

        def is_out_of_memory(self, error):
            return False

    model = Model()
    worker = TranscriptionWorker(root, model_service=model)
    worker._media_service = media
    completed, failed = [], []
    worker.task_completed.connect(completed.append)
    worker.task_failed.connect(lambda *args: failed.append(args))
    worker.start_task(TranscriptionTask(source, tmp_path / "output", None))
    assert not failed
    assert len(completed) == 1
    assert model.calls == 1
    assert Path(completed[0]).read_text(encoding="utf-8") == "pipeline sentinel"
    assert not list((tmp_path / "output").glob("*.partial.txt"))
    assert media._process is None
    assert not worker.is_busy
    assert worker._task_temp_directory is None
