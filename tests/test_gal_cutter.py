from __future__ import annotations

import json
from pathlib import Path
import struct
import wave

import pytest

from src.gal_alignment import AlignmentError, CutterConfig, Unit, cut_ranges, map_units
from src.gal_audio import inspect_wav
from src.gal_cutter import run_cutter
from src.gal_manifest import ManifestError, VoiceJob, alignment_text, load_manifest, lexical
from src.gal_qa import compare


def jobs_file(tmp_path, records):
    path = tmp_path / "batch.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    return path


def record(index, text="嗯。", **extra):
    return {"job_id": f"j{index}", "character_id": "star", "speaker": "star_think" if index % 2 else "star", "language": "zh-CN", "text": text, "output_relpath": f"voice/j{index}.wav", **extra}


def wav_file(path, rate=24000):
    # .2s tone, .4s silence, .2s tone; no resampling in final cuts.
    samples = [12000 if i % 2 else -12000 for i in range(rate // 5)] + [0] * (rate * 2 // 5) + [12000 if i % 2 else -12000 for i in range(rate // 5)]
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return path


@pytest.mark.parametrize("changes,message", [({"character_id": "xia"}, "character_id"), ({"language": "ja-JP"}, "language"), ({"output_relpath": "../../x.wav"}, "输出路径"), ({"text": "<sigh>。"}, "没有可对齐")])
def test_manifest_rejects(tmp_path, changes, message):
    with pytest.raises(ManifestError, match=message):
        load_manifest(jobs_file(tmp_path, [record(1), record(2, **changes)]))


def test_manifest_accepts_same_character_different_speaker_and_tags(tmp_path):
    jobs = load_manifest(jobs_file(tmp_path, [record(1, "等等…… <short pause> 你说什么？"), record(2, "我不知道。 <sigh>")]))
    assert len(jobs) == 2
    assert jobs[0].alignment_text == "等等……  你说什么？"
    assert jobs[1].contains_inline_vocal_event
    assert jobs[0].speaker != jobs[1].speaker


def test_manifest_malformed_missing_and_meta(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(ManifestError, match="JSONL"):
        load_manifest(path)
    with pytest.raises(ManifestError, match="必填"):
        load_manifest(jobs_file(tmp_path, [{"job_id": "x"}]))
    meta = tmp_path / "batch.meta.json"
    meta.write_text(json.dumps({"schema_version": 1, "character_id": "xia"}))
    with pytest.raises(ManifestError, match="metadata"):
        load_manifest(jobs_file(tmp_path, [record(1)]), meta)


@pytest.mark.parametrize("language,text,units", [("zh-CN", "你好，世界。", ["你", "好", "世", "界"]), ("ja-JP", "こんにちは。", ["こん", "にちは"]), ("en-US", "Hello, world!", ["Hello", "world"]), ("zh-CN", "打开 AI 模式。", ["打开", "AI", "模式"])])
def test_language_mapping(tmp_path, language, text, units):
    job = load_manifest(jobs_file(tmp_path, [record(1, text, language=language)]))
    aligned = [Unit(value, i * .1, i * .1 + .08) for i, value in enumerate(units)]
    assert map_units(job, aligned, 3)[0].job.text == text


def test_repeated_lines_map_in_order(tmp_path):
    jobs = load_manifest(jobs_file(tmp_path, [record(1), record(2), record(3)]))
    spans = map_units(jobs, [Unit("嗯", i, i + .2) for i in (0, 1, 2)], 3)
    assert [span.first for span in spans] == [0, 1, 2]


@pytest.mark.parametrize("units", [[Unit("嗯", 0, .2)], [Unit("嗯", 1, 1.2), Unit("嗯", 0, .2)], [Unit("嗯", 0, 0), Unit("嗯", 1, 1.2)], [Unit("嗯", 0, .8), Unit("嗯", .7, 1.2)]])
def test_mapping_rejects_bad_units(tmp_path, units):
    jobs = load_manifest(jobs_file(tmp_path, [record(1), record(2)]))
    with pytest.raises(AlignmentError):
        map_units(jobs, units, 3)


def test_small_overlap_needs_review(tmp_path):
    jobs = load_manifest(jobs_file(tmp_path, [record(1), record(2)]))
    spans = map_units(jobs, [Unit("嗯", 0, 1), Unit("嗯", .98, 1.3)], 2)
    assert [span.status for span in spans] == ["NEEDS_REVIEW", "NEEDS_REVIEW"]


def test_cut_long_silence_and_tagged_event(tmp_path):
    jobs = load_manifest(jobs_file(tmp_path, [record(1, "嗯。"), record(2, "<sigh> 嗯。")]))
    spans = map_units(jobs, [Unit("嗯", .1, .3), Unit("嗯", 2, 2.2)], 3)
    cuts = cut_ranges(spans, 3, [(.4, 1.9)], CutterConfig())
    assert cuts[0][1] == pytest.approx(.44)
    assert cuts[1][0] == pytest.approx(1.15)
    assert cuts[1][2] == "REVIEW_RECOMMENDED"
    assert cuts[0][1] < cuts[1][0]


def test_no_silence_gap_uses_midpoint(tmp_path):
    jobs = load_manifest(jobs_file(tmp_path, [record(1), record(2)]))
    spans = map_units(jobs, [Unit("嗯", 0, .5), Unit("嗯", .6, 1)], 2)
    cuts = cut_ranges(spans, 2, [], CutterConfig(post_roll_ms=300, pre_roll_ms=300))
    assert cuts[0][1] == pytest.approx(.55)
    assert cuts[1][0] == pytest.approx(.55)


class FakeAligner:
    def __init__(self):
        self.calls = 0
    def align(self, audio, text, language):
        self.calls += 1
        assert language == "Chinese"
        return [Unit("嗯", .02, .18), Unit("嗯", .62, .78)]


def test_wav_reports_resume_and_stale(tmp_path):
    audio = wav_file(tmp_path / "batch.wav")
    manifest = jobs_file(tmp_path, [record(1), record(2)])
    output = tmp_path / "out"
    fake = FakeAligner()
    result = run_cutter(audio, manifest, output, aligner=fake)
    assert result["status"] == "COMPLETED"
    assert fake.calls == 1
    assert len(result["lines"]) == 2
    assert inspect_wav(output / "voice/j1.wav")[0] == 24000
    assert all(row["output_sha256"] for row in result["lines"])
    assert (output / "cut_manifest.jsonl").read_text().count("\n") == 2
    assert (output / "qa_report.json").is_file()
    assert run_cutter(audio, manifest, output, aligner=fake, resume=True)["resume_skipped"]
    assert fake.calls == 1
    jobs_file(tmp_path, [record(1, "嗯！"), record(2)])
    changed = run_cutter(audio, manifest, output, aligner=fake, resume=True)
    assert changed["previous_result"] == "STALE"
    assert fake.calls == 2
    run_cutter(audio, manifest, output, aligner=fake, resume=True, config=CutterConfig(post_roll_ms=200))
    assert fake.calls == 3
    wav_file(audio, rate=22050)
    run_cutter(audio, manifest, output, aligner=fake, resume=True, config=CutterConfig(post_roll_ms=200))
    assert fake.calls == 4


def test_qa():
    assert compare("你好，世界！", "你好世界", "zh-CN")["status"] == "PASS"
    assert compare("Hello, world!", "hello world", "en-US")["status"] == "PASS"
    assert compare("岑夏", "晨夏", "zh-CN")["status"] == "REVIEW"
    assert compare("今天我们一起去学校", "今天", "zh-CN")["status"] == "FAIL"
    assert compare("Hello there", "Hello there goodbye everyone", "en-US")["status"] == "FAIL"


def test_duration_guard_and_corrupt_wav(tmp_path):
    manifest = jobs_file(tmp_path, [record(1)])
    audio = tmp_path / "bad.wav"
    audio.write_bytes(b"garbage")
    with pytest.raises(Exception, match="WAV"):
        run_cutter(audio, manifest, tmp_path / "out", aligner=FakeAligner())
    long_audio = tmp_path / "long.wav"
    with wave.open(str(long_audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(1000)
        wav.writeframes(b"\0\0" * 296000)
    with pytest.raises(ValueError, match="295s"):
        run_cutter(long_audio, manifest, tmp_path / "out", aligner=FakeAligner())


def test_cancel_keeps_report_and_no_output(tmp_path):
    import threading
    audio = wav_file(tmp_path / "batch.wav")
    manifest = jobs_file(tmp_path, [record(1), record(2)])
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Exception, match="取消"):
        run_cutter(audio, manifest, tmp_path / "out", aligner=FakeAligner(), cancel=cancel)
    report = json.loads((tmp_path / "out/alignment_report.json").read_text())
    assert report["status"] == "CANCELLED"
    assert not (tmp_path / "out/voice/j1.wav").exists()


def test_forced_aligner_model_catalog(tmp_path, monkeypatch):
    from src import model_catalog as catalog
    monkeypatch.setattr(catalog, "user_models_directory", lambda: tmp_path)
    model = tmp_path / "Qwen3-ForcedAligner-0.6B"
    model.mkdir()
    for name in ("config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.json", "model.safetensors"):
        (model / name).write_bytes(b"x")
    assert catalog.download_target("forced_aligner") == model
    assert catalog.find_installed_model("forced_aligner", tmp_path) == model
    (model / "model.safetensors").unlink()
    assert catalog.find_installed_model("forced_aligner", tmp_path) is None


def test_asr_qa_loads_after_aligner_closes(tmp_path):
    audio = wav_file(tmp_path / "batch.wav")
    manifest = jobs_file(tmp_path, [record(1), record(2)])
    output = tmp_path / "out"
    class Aligner(FakeAligner):
        closed = False
        def close(self):
            self.closed = True
    aligner = Aligner()
    class ASR:
        def load(self):
            assert aligner.closed
        def transcribe(self, path, language):
            assert path.is_file()
            return type("Result", (), {"text": "嗯"})()
        def close(self):
            pass
    report = run_cutter(audio, manifest, output, aligner=aligner, asr_service=ASR())
    assert all(row["state"] == "QA_PASS" for row in report["lines"])
    qa = json.loads((output / "qa_report.json").read_text())
    assert len(qa["lines"]) == 2
