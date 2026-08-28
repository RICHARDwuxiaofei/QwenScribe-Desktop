"""Small filesystem and process-independent helpers."""

from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
import time
from pathlib import Path


TEMP_PREFIX = "QwenASRDesktop_"


def is_process_elevated() -> bool:
    """Return whether Windows is running this process with administrator integrity."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def choose_output_path(input_path: Path, output_directory: Path) -> Path:
    """Choose a non-existing TXT path, accounting for partial output files."""
    output_directory = Path(output_directory)
    stem = Path(input_path).stem
    candidate = output_directory / f"{stem}.txt"
    index = 0
    while (
        candidate.exists()
        or partial_path_for(candidate).exists()
        or reservation_path_for(candidate).exists()
    ):
        index += 1
        candidate = output_directory / f"{stem}_{index:03d}.txt"
    return candidate


def partial_path_for(final_path: Path) -> Path:
    """Return the crash-resilient partial path corresponding to a final path."""
    return final_path.with_name(f"{final_path.stem}.partial.txt")


def reservation_path_for(final_path: Path) -> Path:
    """Return the small exclusive marker used to prevent concurrent collisions."""
    return final_path.with_name(f".{final_path.name}.reserve")


def append_partial(handle: object, text: str, *, has_previous_text: bool) -> bool:
    """Append one non-empty paragraph and durably flush it when possible."""
    cleaned = text.strip()
    if not cleaned:
        return has_previous_text
    if has_previous_text:
        handle.write("\n\n")  # type: ignore[attr-defined]
    handle.write(cleaned)  # type: ignore[attr-defined]
    handle.flush()  # type: ignore[attr-defined]
    try:
        os.fsync(handle.fileno())  # type: ignore[attr-defined]
    except OSError:
        # Some network/removable filesystems do not support fsync; flush still ran.
        pass
    return True


def create_task_temp_directory() -> Path:
    return Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))


def cleanup_stale_temp_directories(*, older_than_hours: float = 24.0) -> int:
    """Remove only this application's stale task directories."""
    temp_root = Path(tempfile.gettempdir())
    cutoff = time.time() - older_than_hours * 3600.0
    removed = 0
    for path in temp_root.glob(f"{TEMP_PREFIX}*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
                removed += 1
        except OSError:
            continue
    return removed
