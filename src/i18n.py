"""Small dependency-free UI translation catalog for Chinese and English."""

from __future__ import annotations

import re


DEFAULT_UI_LANGUAGE = "zh_CN"
UI_LANGUAGES = (("简体中文", "zh_CN"), ("English", "en_US"))

STATIC_EN = {
    "● 完全本地 · 不上传": "● Fully local · No uploads",
    "正在后台检测所选推理设备…": "Detecting the selected inference device…",
    "队列为空": "Queue is empty",
    "设备": "Device",
    "任务": "Tasks",
    "界面语言": "Interface",
    "模型在独立后台进程中驻留，多个文件顺序复用同一模型。": "The model stays in an isolated background process and is reused sequentially.",
    "本地视频 / 音频转文字": "Local Video / Audio Transcription",
    "Qwen3-ASR-1.7B · UTF-8 TXT · 无时间戳 · 单 GPU 顺序处理": "Qwen3-ASR-1.7B · UTF-8 TXT · No timestamps · Single-GPU queue",
    "输出目录": "Output folder",
    "选择 TXT 输出目录": "Choose the TXT output folder",
    "选择目录": "Browse",
    "语言": "Audio language",
    "推理方式": "Backend",
    "官方 Transformers（PyTorch CUDA）": "Official Transformers (PyTorch CUDA)",
    "模型": "Model",
    "Qwen3-ASR-1.7B 官方 BF16/FP16": "Qwen3-ASR-1.7B official BF16/FP16",
    "开始转写队列": "Start transcription queue",
    "取消当前任务": "Cancel current task",
    "打开输出目录": "Open output folder",
    "就绪": "Ready",
    "主要运行状态会显示在这里；完整异常写入用户日志文件。": "Key status messages appear here; full exceptions are written to the user log.",
    "+ 添加文件": "+ Add files",
    "+ 添加文件夹": "+ Add folder",
    "移除选中": "Remove selected",
    "清空队列": "Clear queue",
    "结果预览": "Result preview",
    "选择队列中的文件；完成或保留 partial 后可在这里预览。": "Select a queued file to preview completed or retained partial text.",
    "将视频或音频拖到这里": "Drop video or audio here",
    "支持单个或多个文件；全部任务在本地按顺序处理": "One or more files; all tasks run locally and sequentially",
    "选择文件": "Choose files",
    "选择文件夹": "Choose folder",
}

ASR_LANGUAGE_EN = {
    "自动识别": "Auto detect",
    "中文": "Chinese",
    "英语": "English",
    "日语": "Japanese",
    "德语": "German",
    "粤语": "Cantonese",
    "韩语": "Korean",
    "法语": "French",
    "西班牙语": "Spanish",
    "葡萄牙语": "Portuguese",
    "俄语": "Russian",
    "意大利语": "Italian",
    "阿拉伯语": "Arabic",
    "泰语": "Thai",
    "越南语": "Vietnamese",
}

STATUS_EN = {
    "等待中": "Pending",
    "处理中": "Processing",
    "已完成": "Completed",
    "错误": "Error",
    "已取消": "Cancelled",
}

RUNTIME_EN = {
    "正在保存文本": "Saving text",
    "已完成": "Completed",
    "已取消": "Cancelled",
    "发生错误": "An error occurred",
    "正在检查文件": "Checking file",
    "正在检查输入文件和音频轨道…": "Checking the input file and audio stream…",
    "正在提取音频": "Extracting audio",
    "正在提取 16 kHz 单声道音频…": "Extracting 16 kHz mono audio…",
    "正在检测静音": "Detecting silence",
    "正在检测静音并计算分段…": "Detecting silence and calculating segments…",
    "正在加载模型": "Loading model",
    "正在加载 Qwen3-ASR-1.7B；首次运行可能需要下载数 GB 文件…": "Loading Qwen3-ASR-1.7B; the first run may require a multi-GB download…",
    "正在复用已加载的模型…": "Reusing the loaded model…",
    "当前片段识别失败，正在自动重试一次…": "The current segment failed; retrying once…",
    "队列为空": "Queue is empty",
    "所选推理设备不可用": "The selected inference device is unavailable",
}


def normalize_ui_language(value: object) -> str:
    return "en_US" if str(value) == "en_US" else DEFAULT_UI_LANGUAGE


def static_text(chinese: str, ui_language: str) -> str:
    return STATIC_EN.get(chinese, chinese) if ui_language == "en_US" else chinese


def asr_language_text(chinese_label: str, ui_language: str) -> str:
    return ASR_LANGUAGE_EN.get(chinese_label, chinese_label) if ui_language == "en_US" else chinese_label


def queue_status_text(chinese: str, ui_language: str) -> str:
    return STATUS_EN.get(chinese, chinese) if ui_language == "en_US" else chinese


def runtime_text(message: str, ui_language: str) -> str:
    """Translate common live statuses while preserving paths and unknown errors."""
    if ui_language != "en_US":
        return message
    if message in RUNTIME_EN:
        return RUNTIME_EN[message]
    patterns = (
        (r"^正在识别第 (\d+)/(\d+) 段$", r"Transcribing segment \1/\2"),
        (r"^转写完成：(.*)$", r"Transcription completed: \1"),
        (r"^已取消，已识别内容保存在：(.*)$", r"Cancelled; recognized text was saved to: \1"),
        (r"^已加入 (\d+) 个文件；本地 GPU 将逐个处理。$", r"Added \1 file(s); the local GPU will process them sequentially."),
        (r"^设备检测完成：CUDA (\d+) 个，Vulkan (\d+) 个。$", r"Device scan complete: \1 CUDA, \2 Vulkan."),
    )
    for pattern, replacement in patterns:
        if re.match(pattern, message):
            return re.sub(pattern, replacement, message)
    return message
