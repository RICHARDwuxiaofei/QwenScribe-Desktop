import subprocess
import sys
import threading

import pytest

from src.exceptions import MediaProcessingError, UserCancelledError
from src.media_service import MediaService


@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(MediaService, "_find_executable", lambda *args: sys.executable)
    return MediaService(tmp_path)


def test_progress_callback_failure_reaps_child(media, monkeypatch):
    real_popen = subprocess.Popen
    children = []

    def popen(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr("src.media_service.subprocess.Popen", popen)

    def fail_progress(value):
        raise RuntimeError("consumer failed")

    try:
        with pytest.raises(RuntimeError, match="consumer failed"):
            media._run_streaming_progress(
                [sys.executable, "-u", "-c", "import time; print('out_time_ms=1'); time.sleep(30)"],
                1, threading.Event(), fail_progress, "failed",
            )
        assert children[0].poll() is not None
        assert children[0].stdout.closed
        assert media._process is None
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            child.stdout.close()


@pytest.mark.parametrize("streaming", [True, False])
def test_pre_cancelled_command_never_starts_child(media, monkeypatch, streaming):
    calls = []
    monkeypatch.setattr("src.media_service.subprocess.Popen", lambda *a, **k: calls.append(a))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(UserCancelledError):
        if streaming:
            media._run_streaming_progress([], 1, cancel, lambda value: None, "failed")
        else:
            media._run_capture([], cancel, "failed")
    assert not calls


@pytest.mark.parametrize("duration", ["NaN", "Infinity", "-Infinity"])
def test_probe_rejects_nonfinite_duration(media, tmp_path, monkeypatch, duration):
    source = tmp_path / "source.wav"
    source.touch()
    monkeypatch.setattr(media, "_run_capture", lambda *args: (
        '{"streams":[{"codec_type":"audio"}],"format":{"duration":"' + duration + '"}}'
    ))
    with pytest.raises(MediaProcessingError):
        media.probe(source, threading.Event())
