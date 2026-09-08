"""Chinese UI labels mapped to Qwen3-ASR canonical language names."""

from __future__ import annotations

from collections import OrderedDict


LANGUAGE_MAP: "OrderedDict[str, str | None]" = OrderedDict(
    [
        ("自动识别", None),
        ("中文", "Chinese"),
        ("英语", "English"),
        ("日语", "Japanese"),
        ("德语", "German"),
        ("粤语", "Cantonese"),
        ("韩语", "Korean"),
        ("法语", "French"),
        ("西班牙语", "Spanish"),
        ("葡萄牙语", "Portuguese"),
        ("俄语", "Russian"),
        ("意大利语", "Italian"),
        ("阿拉伯语", "Arabic"),
        ("泰语", "Thai"),
        ("越南语", "Vietnamese"),
        ("印度尼西亚语", "Indonesian"),
        ("土耳其语", "Turkish"),
        ("印地语", "Hindi"),
        ("马来语", "Malay"),
        ("荷兰语", "Dutch"),
        ("瑞典语", "Swedish"),
        ("丹麦语", "Danish"),
        ("芬兰语", "Finnish"),
        ("波兰语", "Polish"),
        ("捷克语", "Czech"),
        ("菲律宾语", "Filipino"),
        ("波斯语", "Persian"),
        ("希腊语", "Greek"),
        ("匈牙利语", "Hungarian"),
        ("马其顿语", "Macedonian"),
        ("罗马尼亚语", "Romanian"),
    ]
)


# transcribe-cpp 0.1.3 validates BCP-47 codes before constructing the Qwen
# language prompt; Transformers instead accepts the canonical names above.
VULKAN_LANGUAGE_CODES = {
    "Chinese": "zh", "English": "en", "Cantonese": "yue",
    "Arabic": "ar", "German": "de", "French": "fr", "Spanish": "es",
    "Portuguese": "pt", "Indonesian": "id", "Italian": "it", "Korean": "ko",
    "Russian": "ru", "Thai": "th", "Vietnamese": "vi", "Japanese": "ja",
    "Turkish": "tr", "Hindi": "hi", "Malay": "ms", "Dutch": "nl",
    "Swedish": "sv", "Danish": "da", "Finnish": "fi", "Polish": "pl",
    "Czech": "cs", "Filipino": "fil", "Persian": "fa", "Greek": "el",
    "Romanian": "ro", "Hungarian": "hu", "Macedonian": "mk",
}


def vulkan_language_hint(language: str | None) -> str | None:
    """Adapt canonical UI names while retaining None and explicit worker codes."""
    return VULKAN_LANGUAGE_CODES.get(language, language)


def language_for_label(label: str) -> str | None:
    """Return the canonical model language for a UI label."""
    if label not in LANGUAGE_MAP:
        raise ValueError(f"不支持的语言选项：{label}")
    return LANGUAGE_MAP[label]


def valid_label_or_default(label: object) -> str:
    """Return a persisted label if valid, otherwise the auto-detect label."""
    return str(label) if isinstance(label, str) and label in LANGUAGE_MAP else "自动识别"
