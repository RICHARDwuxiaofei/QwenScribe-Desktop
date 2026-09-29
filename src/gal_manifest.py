"""Ordered, script-authoritative Gal TTS batch contract."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

LANGUAGES = {"zh-CN": "Chinese", "ja-JP": "Japanese", "en-US": "English"}
TAG = re.compile(r"<[^<>]+>")


class ManifestError(ValueError):
    pass


def alignment_text(text: str) -> str:
    return TAG.sub("", text).strip()


def lexical(text: str) -> str:
    return "".join(char.casefold() for char in text if char.isalnum())


@dataclass(frozen=True)
class VoiceJob:
    job_id: str
    character_id: str
    speaker: str
    language: str
    text: str
    output_relpath: str
    alignment_text: str
    contains_inline_vocal_event: bool


def safe_output_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ManifestError(f"不安全的输出路径：{value!r}")
    path = PurePosixPath(value)
    if any(part in (".", "..") for part in value.split("/")) or path.suffix.lower() != ".wav":
        raise ManifestError(f"不安全或非 WAV 输出路径：{value!r}")
    return path


def load_manifest(path: Path, meta_path: Path | None = None) -> list[VoiceJob]:
    jobs: list[VoiceJob] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise ManifestError(f"无法读取 JSONL：{error}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ManifestError(f"JSONL 第 {number} 行无效：{error}") from error
        if not isinstance(item, dict):
            raise ManifestError(f"JSONL 第 {number} 行必须是对象")
        required = ("job_id", "character_id", "speaker", "language", "text")
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in required):
            raise ManifestError(f"JSONL 第 {number} 行缺少必填字段：{required}")
        output = item.get("target_output_relpath") or item.get("output_relpath")
        if not isinstance(output, str):
            raise ManifestError(f"JSONL 第 {number} 行缺少 output_relpath")
        safe_output_path(output)
        if item["language"] not in LANGUAGES:
            raise ManifestError(f"不支持的语言：{item['language']}")
        cleaned = alignment_text(item["text"])
        if not lexical(cleaned):
            raise ManifestError(f"JSONL 第 {number} 行没有可对齐的文字")
        if item["job_id"] in seen_ids or output in seen_paths:
            raise ManifestError(f"JSONL 第 {number} 行有重复 job_id 或输出路径")
        seen_ids.add(item["job_id"])
        seen_paths.add(output)
        jobs.append(VoiceJob(item["job_id"], item["character_id"], item["speaker"], item["language"], item["text"], output, cleaned, bool(TAG.search(item["text"]))))
    if not jobs:
        raise ManifestError("batch JSONL 没有 voice job")
    if len({job.character_id for job in jobs}) != 1:
        raise ManifestError("batch 混入多个 character_id")
    if len({job.language for job in jobs}) != 1:
        raise ManifestError("batch 混入多种 language")
    if meta_path is not None:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ManifestError(f"batch metadata 无效：{error}") from error
        if not isinstance(meta, dict) or meta.get("schema_version") != 1:
            raise ManifestError("不支持的 batch metadata schema_version")
        for key, actual in (("character_id", jobs[0].character_id), ("language", jobs[0].language), ("jobs_file", path.name)):
            if key in meta and meta[key] != actual:
                raise ManifestError(f"batch metadata {key} 与输入不一致")
    return jobs
