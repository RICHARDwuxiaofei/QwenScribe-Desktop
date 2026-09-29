"""Deterministic Gal TTS alignment, PCM cutting, resume and reports."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import threading
from typing import Callable

from .forced_aligner_service import ForcedAlignerService
from .gal_alignment import CutterConfig, map_units, cut_ranges
from .gal_audio import inspect_wav, find_silences, slice_wav
from .gal_manifest import LANGUAGES, load_manifest, safe_output_path
from .gal_qa import compare
from .model_catalog import FORCED_ALIGNER_MODEL_ID

SCHEMA_VERSION = 1


class CutterCancelled(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(audio_hash: str, jobs: list, config: CutterConfig) -> str:
    payload = {"schema_version": SCHEMA_VERSION, "master_sha256": audio_hash, "jobs": [{"job_id": j.job_id, "character_id": j.character_id, "language": j.language, "text": j.text, "output_relpath": j.output_relpath} for j in jobs], "model_id": FORCED_ALIGNER_MODEL_ID, "config": asdict(config)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + ".part")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def run_cutter(audio: Path, manifest: Path, output_root: Path, *, meta: Path | None = None, config: CutterConfig | None = None, aligner: ForcedAlignerService | None = None, asr_service=None, resume: bool = False, cancel: threading.Event | None = None, progress: Callable[[int, int, str], None] | None = None) -> dict:
    config = config or CutterConfig()
    config.validate()
    cancel = cancel or threading.Event()
    jobs = load_manifest(manifest, meta)
    rate, channels, width, frames, duration = inspect_wav(audio)
    if duration > 295:
        raise ValueError(f"master WAV {duration:.1f}s 超过 Forced Aligner 295s 保护线；请在生成端拆 batch（建议 ≤240s）")
    if meta:
        metadata = json.loads(meta.read_text(encoding="utf-8"))
        if metadata.get("audio_file", audio.name) != audio.name:
            raise ValueError("batch metadata audio_file 与 master 不匹配")
        if metadata.get("input_sha256") and metadata["input_sha256"] != sha256(audio):
            raise ValueError("batch metadata input_sha256 与 master 不匹配")
    output_root.mkdir(parents=True, exist_ok=True)
    # A report is kept at the selected root; different batches must use distinct roots.
    report_path = output_root / "alignment_report.json"
    cut_path = output_root / "cut_manifest.jsonl"
    qa_path = output_root / "qa_report.json"
    input_hash = sha256(audio)
    config_hash = fingerprint(input_hash, jobs, config)
    old = None
    if resume and report_path.is_file():
        try:
            old = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = None
    qa_ready = asr_service is None
    if asr_service is not None and qa_path.is_file():
        try:
            old_qa = json.loads(qa_path.read_text(encoding="utf-8"))
            qa_ready = bool(old_qa.get("enabled") and len(old_qa.get("lines", [])) == len(jobs))
        except (OSError, json.JSONDecodeError, AttributeError):
            qa_ready = False
    if old and old.get("config_hash") == config_hash and old.get("status") in ("COMPLETED", "NEEDS_REVIEW") and qa_ready:
        rows = old.get("lines", [])
        if len(rows) == len(jobs) and all((output_root / safe_output_path(row["output_relpath"])).is_file() and sha256(output_root / safe_output_path(row["output_relpath"])) == row.get("output_sha256") for row in rows):
            return {**old, "resume_skipped": True}
    stale_reason = None
    if resume and old:
        stale_reason = "输入文本、master 或配置已变化" if old.get("config_hash") != config_hash else "输出 WAV 缺失、hash 不匹配或 QA 未完成"
    report = {"schema_version": SCHEMA_VERSION, "status": "PENDING", "previous_result": "STALE" if stale_reason else None, "stale_reason": stale_reason, "master": str(audio.resolve()), "master_sha256": input_hash, "duration": duration, "sample_rate": rate, "channels": channels, "sample_width": width, "character_id": jobs[0].character_id, "language": jobs[0].language, "model_id": FORCED_ALIGNER_MODEL_ID, "config": asdict(config), "config_hash": config_hash, "lines": []}
    _write_json(report_path, report)
    cut_path.write_text("", encoding="utf-8")
    _write_json(qa_path, {"enabled": asr_service is not None, "lines": []})
    service = aligner or ForcedAlignerService()
    try:
        if cancel.is_set():
            raise CutterCancelled("用户取消")
        transcript = "\n".join(job.alignment_text for job in jobs)
        try:
            units = service.align(audio, transcript, LANGUAGES[jobs[0].language])
        except Exception:
            if cancel.is_set():
                raise CutterCancelled("用户取消")
            raise
        if cancel.is_set():
            raise CutterCancelled("用户取消")
        spans = map_units(jobs, units, duration)
        silences = find_silences(audio, config.silence_threshold_db, config.min_silence_ms) if config.fine_silence else []
        ranges = cut_ranges(spans, duration, silences, config)
        for index, (span, (start, end, status)) in enumerate(zip(spans, ranges)):
            if cancel.is_set():
                raise CutterCancelled("用户取消")
            target = output_root / safe_output_path(span.job.output_relpath)
            # Refuse symlink escapes from an existing output tree.
            if not target.resolve().is_relative_to(output_root.resolve()):
                raise ValueError(f"输出路径逃逸：{target}")
            clip_duration, clip_rate = slice_wav(audio, target, start, end)
            row = {"job_id": span.job.job_id, "text": span.job.text, "alignment_text": span.job.alignment_text, "first_unit_start": span.first, "last_unit_end": span.last, "cut_start": start, "cut_end": end, "duration": clip_duration, "sample_rate": clip_rate, "alignment_status": status, "contains_inline_vocal_event": span.job.contains_inline_vocal_event, "diagnostic": span.diagnostic, "output_relpath": span.job.output_relpath, "output_sha256": sha256(target), "source_master": str(audio.resolve()), "config_hash": config_hash, "model_id": FORCED_ALIGNER_MODEL_ID, "state": "CUT" if status == "PASS" else "NEEDS_REVIEW"}
            report["lines"].append(row)
            report["status"] = "PROCESSING"
            _write_json(report_path, report)
            cut_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in report["lines"]), encoding="utf-8")
            if progress:
                progress(index + 1, len(jobs), span.job.job_id)
        cut_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in report["lines"]), encoding="utf-8")
        report["status"] = "NEEDS_REVIEW" if any(row["alignment_status"] != "PASS" for row in report["lines"]) else "COMPLETED"
        _write_json(report_path, report)
    except CutterCancelled:
        report["status"] = "CANCELLED"
        _write_json(report_path, report)
        raise
    except Exception as error:
        report["status"] = "ALIGNMENT_FAILED" if not report["lines"] else "FAILED"
        report["diagnostic"] = str(error)
        _write_json(report_path, report)
        raise
    finally:
        close = getattr(service, "close", None)
        if close:
            close()
    qa = {"enabled": asr_service is not None, "lines": []}
    _write_json(qa_path, qa)
    if asr_service is not None:
        try:
            asr_service.load()
            for row, job in zip(report["lines"], jobs):
                if cancel.is_set():
                    raise CutterCancelled("用户取消")
                result = asr_service.transcribe(output_root / safe_output_path(job.output_relpath), LANGUAGES[job.language])
                qa["lines"].append({"job_id": job.job_id, **compare(job.text, result.text, job.language)})
                _write_json(qa_path, qa)
                row["qa_status"] = qa["lines"][-1]["status"]
                row["state"] = "QA_" + qa["lines"][-1]["status"]
                _write_json(report_path, report)
            if any(item["status"] != "PASS" for item in qa["lines"]):
                report["status"] = "NEEDS_REVIEW"
                _write_json(report_path, report)
        except Exception as error:
            qa["error"] = str(error)
            _write_json(qa_path, qa)
            report["status"] = "QA_FAILED"
            report["diagnostic"] = str(error)
            _write_json(report_path, report)
            raise
        finally:
            asr_service.close()
        cut_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in report["lines"]), encoding="utf-8")
    return report
