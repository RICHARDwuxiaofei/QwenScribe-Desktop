from src.i18n import (
    asr_language_text,
    normalize_ui_language,
    queue_status_text,
    runtime_text,
    static_text,
)


def test_ui_language_normalization_defaults_to_chinese() -> None:
    assert normalize_ui_language(None) == "zh_CN"
    assert normalize_ui_language("unexpected") == "zh_CN"
    assert normalize_ui_language("en_US") == "en_US"


def test_static_and_asr_language_translation() -> None:
    assert static_text("选择文件", "en_US") == "Choose files"
    assert asr_language_text("自动识别", "en_US") == "Auto detect"
    assert asr_language_text("日语", "en_US") == "Japanese"


def test_status_and_runtime_translation_preserve_dynamic_values() -> None:
    assert queue_status_text("处理中", "en_US") == "Processing"
    assert runtime_text("正在识别第 8/41 段", "en_US") == "Transcribing segment 8/41"
    assert runtime_text("转写完成：D:\\out\\demo.txt", "en_US").endswith(
        "D:\\out\\demo.txt"
    )
