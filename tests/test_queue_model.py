from __future__ import annotations

from pathlib import Path

from src.queue_model import QueueStatus, TranscriptionQueue, format_file_size


def test_queue_adds_existing_files_and_deduplicates(tmp_path: Path) -> None:
    media = tmp_path / "会议.mp4"
    media.write_bytes(b"123")
    queue = TranscriptionQueue()

    assert queue.add_paths([media, media]) == 1
    assert len(queue.entries) == 1
    assert queue.entries[0].path == media.resolve()


def test_queue_reset_and_summary(tmp_path: Path) -> None:
    first = tmp_path / "a.mp3"
    second = tmp_path / "b.wav"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    queue = TranscriptionQueue()
    queue.add_paths([first, second])
    queue.entries[0].status = QueueStatus.COMPLETED
    queue.entries[1].status = QueueStatus.ERROR

    assert queue.summary() == (2, 1, 1, 0)
    queue.reset_all()
    assert all(entry.status is QueueStatus.PENDING for entry in queue.entries)


def test_queue_removes_selected_indices(tmp_path: Path) -> None:
    paths = [tmp_path / f"{index}.wav" for index in range(3)]
    for path in paths:
        path.write_bytes(b"x")
    queue = TranscriptionQueue()
    queue.add_paths(paths)
    queue.remove_indices([1])
    assert [entry.path.name for entry in queue.entries] == ["0.wav", "2.wav"]


def test_format_file_size() -> None:
    assert format_file_size(0) == "0 B"
    assert format_file_size(1536) == "1.5 KB"
    assert format_file_size(3 * 1024**3) == "3.0 GB"
