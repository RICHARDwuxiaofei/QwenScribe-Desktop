from pathlib import Path
from types import SimpleNamespace
import threading

from src.model_service import TranscriptionResult
from src.transcription_worker import TranscriptionTask, TranscriptionWorker
from test_transcription_worker_duration import _EstimatedAacMediaService


def test_cancel_during_last_inference_retains_partial_and_allows_restart(tmp_path):
    class Model:
        is_loaded = True
        cancel = True

        def transcribe(self, path, language):
            if self.cancel:
                worker.request_cancel()
            return TranscriptionResult("最后一句", None)

        def is_out_of_memory(self, error):
            return False

    class Media(_EstimatedAacMediaService):
        def probe(self, path, event):
            from src.media_service import MediaInfo
            return MediaInfo(1.0, 1)

        def cancel_current_process(self):
            pass

    model = Model()
    worker = TranscriptionWorker(tmp_path, model_service=model)
    worker._media_service = Media()
    completed, cancelled, failed = [], [], []
    worker.task_completed.connect(completed.append)
    worker.task_cancelled.connect(cancelled.append)
    worker.task_failed.connect(lambda *args: failed.append(args))
    task = TranscriptionTask(tmp_path / "input.wav", tmp_path, None)
    worker.start_task(task)
    assert not failed
    assert not completed
    assert len(cancelled) == 1
    assert Path(cancelled[0]).read_text(encoding="utf-8") == "最后一句"
    assert not (tmp_path / "input.txt").exists()
    model.cancel = False
    worker.mark_task_pending()
    worker.start_task(task)
    assert len(completed) == 1
    assert Path(completed[0]).read_text(encoding="utf-8") == "最后一句"
    assert not worker.is_busy


def test_terminal_signal_is_sent_after_cleanup_and_preserves_next_pending_cancel(tmp_path):
    worker = TranscriptionWorker(tmp_path, model_service=object())
    worker._media_service = SimpleNamespace(cancel_current_process=lambda: None)
    worker._execute_task = lambda task: None
    states = []

    def completed(path):
        states.append((worker.is_busy, worker._task_temp_directory))
        worker.mark_task_pending()
        worker.request_cancel()

    worker.task_completed.connect(completed)
    worker.start_task(TranscriptionTask(tmp_path / "input.wav", tmp_path, None))
    assert states == [(False, None)]
    assert worker._task_pending
    assert worker._pending_cancel


def test_oom_split_writes_each_successful_range_once(tmp_path):
    class Model:
        is_loaded = True

        def transcribe(self, path, language):
            start, end = media.created_ranges[-1]
            if end - start > 100:
                raise MemoryError("synthetic OOM")
            return TranscriptionResult(f"{start}:{end}", None)

        def is_out_of_memory(self, error):
            return isinstance(error, MemoryError)

        def clear_cuda_cache(self):
            pass

    media = _EstimatedAacMediaService()
    worker = TranscriptionWorker(tmp_path, model_service=Model())
    worker._media_service = media
    completed, failed = [], []
    worker.task_completed.connect(completed.append)
    worker.task_failed.connect(lambda *args: failed.append(args))
    worker.start_task(TranscriptionTask(tmp_path / "input.aac", tmp_path, None))
    assert not failed
    assert len(completed) == 1
    ranges = [tuple(map(float, line.split(":"))) for line in Path(completed[0]).read_text().split("\n\n")]
    assert ranges[0][0] == 0
    assert ranges[-1][1] == 500
    assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))
    assert sum(end - start for start, end in ranges) == 500


def test_cancel_immediately_after_busy_transition_is_not_cleared(tmp_path):
    worker = TranscriptionWorker(tmp_path, model_service=object())
    worker._media_service = SimpleNamespace(cancel_current_process=lambda: None)
    executed, cancelled = [], []
    worker._execute_task = lambda task: executed.append(task)
    worker.task_cancelled.connect(cancelled.append)

    class CancelAfterUnlock:
        lock = threading.Lock()
        first = True

        def __enter__(self):
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()
            if self.first:
                self.first = False
                worker.request_cancel()

    worker._busy_lock = CancelAfterUnlock()
    worker.start_task(TranscriptionTask(tmp_path / "input.wav", tmp_path, None))
    assert cancelled == [""]
    assert not executed
