"""Qt-independent batch queue state used by the desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class QueueStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class QueueEntry:
    path: Path
    size_bytes: int
    status: QueueStatus = QueueStatus.PENDING
    progress: int = 0
    result_path: Path | None = None
    error: str = ""

    def reset(self) -> None:
        self.status = QueueStatus.PENDING
        self.progress = 0
        self.result_path = None
        self.error = ""


class TranscriptionQueue:
    """Maintain stable ordering and Windows-friendly duplicate detection."""

    def __init__(self) -> None:
        self.entries: list[QueueEntry] = []

    def add_paths(self, paths: Iterable[Path]) -> int:
        existing = {str(entry.path).casefold() for entry in self.entries}
        added = 0
        for raw_path in paths:
            path = Path(raw_path).resolve()
            key = str(path).casefold()
            if key in existing or not path.is_file():
                continue
            self.entries.append(QueueEntry(path=path, size_bytes=path.stat().st_size))
            existing.add(key)
            added += 1
        return added

    def remove_indices(self, indices: Iterable[int]) -> None:
        remove = set(indices)
        self.entries = [entry for index, entry in enumerate(self.entries) if index not in remove]

    def clear(self) -> None:
        self.entries.clear()

    def reset_all(self) -> None:
        for entry in self.entries:
            entry.reset()

    def summary(self) -> tuple[int, int, int, int]:
        total = len(self.entries)
        completed = sum(entry.status is QueueStatus.COMPLETED for entry in self.entries)
        failed = sum(entry.status is QueueStatus.ERROR for entry in self.entries)
        cancelled = sum(entry.status is QueueStatus.CANCELLED for entry in self.entries)
        return total, completed, failed, cancelled


def format_file_size(size_bytes: int) -> str:
    value = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"
