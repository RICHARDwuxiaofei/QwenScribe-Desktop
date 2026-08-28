from __future__ import annotations

from pathlib import Path

from src.utils import choose_output_path, partial_path_for


def test_output_path_when_file_does_not_exist(tmp_path: Path) -> None:
    result = choose_output_path(Path("meeting.mkv"), tmp_path)
    assert result == tmp_path / "meeting.txt"


def test_output_path_when_base_exists(tmp_path: Path) -> None:
    (tmp_path / "meeting.txt").write_text("existing", encoding="utf-8")
    result = choose_output_path(Path("meeting.mkv"), tmp_path)
    assert result == tmp_path / "meeting_001.txt"


def test_output_path_when_multiple_numbered_files_exist(tmp_path: Path) -> None:
    for name in ("meeting.txt", "meeting_001.txt", "meeting_002.txt"):
        (tmp_path / name).write_text("existing", encoding="utf-8")
    result = choose_output_path(Path("meeting.mkv"), tmp_path)
    assert result == tmp_path / "meeting_003.txt"


def test_output_path_supports_chinese_name_and_partial_collision(tmp_path: Path) -> None:
    base = tmp_path / "会议记录.txt"
    partial_path_for(base).write_text("partial", encoding="utf-8")
    result = choose_output_path(Path("会议记录.mp4"), tmp_path)
    assert result == tmp_path / "会议记录_001.txt"
