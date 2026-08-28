from __future__ import annotations

from src.language_map import language_for_label


def test_auto_detect_maps_to_none() -> None:
    assert language_for_label("自动识别") is None


def test_chinese_maps_to_canonical_name() -> None:
    assert language_for_label("中文") == "Chinese"


def test_japanese_maps_to_canonical_name() -> None:
    assert language_for_label("日语") == "Japanese"
