from __future__ import annotations

from src.segmenter import calculate_segments


def _assert_contiguous(segments: list, duration: float) -> None:
    assert abs(segments[0].start - 0.0) < 1e-9
    assert abs(segments[-1].end - duration) < 1e-9
    for left, right in zip(segments, segments[1:]):
        assert abs(left.end - right.start) < 1e-9


def test_prefers_silence_midpoints_near_target() -> None:
    segments = calculate_segments(500.0, [(168.0, 172.0), (344.0, 350.0)])
    assert [(s.start, s.end) for s in segments] == [
        (0.0, 170.0),
        (170.0, 347.0),
        (347.0, 500.0),
    ]


def test_without_silence_uses_hard_target_cut() -> None:
    segments = calculate_segments(600.0, [])
    assert [s.end for s in segments] == [180.0, 360.0, 600.0]
    _assert_contiguous(segments, 600.0)


def test_short_final_segment_is_merged() -> None:
    segments = calculate_segments(260.0, [(230.0, 240.0)])
    assert len(segments) == 1
    assert abs(segments[0].duration - 260.0) < 1e-9


def test_two_hour_audio_is_split_without_overlap() -> None:
    segments = calculate_segments(2 * 60 * 60, [])
    assert len(segments) == 40
    assert all(segment.duration <= 240.0 for segment in segments)
    assert abs(sum(segment.duration for segment in segments) - 7200.0) < 1e-9
    _assert_contiguous(segments, 7200.0)


def test_empty_silence_list_and_short_audio() -> None:
    segments = calculate_segments(75.0, [])
    assert len(segments) == 1
    assert segments[0].start == 0.0
    assert segments[0].end == 75.0
