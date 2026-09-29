"""Conservative sequential mapping and silence refined line boundaries."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .gal_manifest import VoiceJob, lexical


class AlignmentError(ValueError):
    pass


@dataclass(frozen=True)
class Unit:
    text: str
    start_time: float
    end_time: float


@dataclass(frozen=True)
class LineSpan:
    job: VoiceJob
    first: float
    last: float
    status: str = "PASS"
    diagnostic: str = ""


def map_units(jobs: list[VoiceJob], units: Iterable[Unit], duration: float) -> list[LineSpan]:
    """Consume the model's lexical stream in manifest order, including duplicates."""
    source = list(units)
    if not source:
        raise AlignmentError("Forced Aligner 没有返回任何 unit")
    expected = "".join(lexical(job.alignment_text) for job in jobs)
    actual = "".join(lexical(unit.text) for unit in source)
    if actual != expected:
        raise AlignmentError(f"对齐文字不匹配：expected={expected[:120]!r}, actual={actual[:120]!r}")
    previous_start = -1.0
    for unit in source:
        if not lexical(unit.text):
            raise AlignmentError(f"空 lexical unit：{unit.text!r}")
        if not all(math.isfinite(v) for v in (unit.start_time, unit.end_time)) or unit.start_time < 0 or unit.end_time <= unit.start_time or unit.end_time > duration + .05:
            raise AlignmentError(f"无效时间戳：{unit}")
        if unit.start_time < previous_start:
            raise AlignmentError(f"时间戳非单调：{unit}")
        previous_start = unit.start_time
    spans: list[LineSpan] = []
    cursor = 0
    for job in jobs:
        target = lexical(job.alignment_text)
        collected = ""
        first_index = cursor
        while len(collected) < len(target) and cursor < len(source):
            collected += lexical(source[cursor].text)
            cursor += 1
        if collected != target:
            raise AlignmentError(f"job {job.job_id} 的 unit 跨句或数量不匹配：{collected!r} != {target!r}")
        slow = [unit for unit in source[first_index:cursor] if unit.end_time - unit.start_time > 2.5]
        spans.append(LineSpan(job, source[first_index].start_time, source[cursor - 1].end_time,
                              "NEEDS_REVIEW" if slow else "PASS",
                              "存在超过 2.5s 的单个 lexical unit，可能未正确对齐" if slow else ""))
    if cursor != len(source):
        raise AlignmentError("Forced Aligner 返回多余 unit")
    result = list(spans)
    for index in range(1, len(spans)):
        span = spans[index]
        if spans[index - 1].last > span.first:
            overlap = spans[index - 1].last - span.first
            if overlap > .04:
                raise AlignmentError(f"相邻台词明显重叠：{spans[index-1].job.job_id} / {span.job.job_id}，{overlap:.3f}s")
            diagnostic = f"相邻时间戳轻微重叠 {overlap:.3f}s"
            prior = result[index - 1]
            result[index - 1] = LineSpan(prior.job, prior.first, prior.last, "NEEDS_REVIEW", diagnostic)
            result[index] = LineSpan(span.job, span.first, span.last, "NEEDS_REVIEW", diagnostic)
    return result


@dataclass(frozen=True)
class CutterConfig:
    silence_threshold_db: float = -40
    min_silence_ms: int = 80
    pre_roll_ms: int = 70
    post_roll_ms: int = 140
    tagged_event_padding_ms: int = 400
    fine_silence: bool = True

    def validate(self) -> None:
        if not -100 <= self.silence_threshold_db <= -10 or not 20 <= self.min_silence_ms <= 1000 or any(v < 0 or v > 3000 for v in (self.pre_roll_ms, self.post_roll_ms, self.tagged_event_padding_ms)):
            raise ValueError("Gal Cutter 配置超出安全范围")


def cut_ranges(spans: list[LineSpan], duration: float, silences: list[tuple[float, float]], config: CutterConfig) -> list[tuple[float, float, str]]:
    config.validate()
    boundaries: list[float] = []
    for left, right in zip(spans, spans[1:]):
        gap_start, gap_end = left.last, right.first
        if gap_end < gap_start:
            boundaries.append((gap_start + gap_end) / 2)
            continue
        candidates = [(max(a, gap_start), min(b, gap_end)) for a, b in silences if b > gap_start and a < gap_end]
        candidates = [(a, b) for a, b in candidates if b > a]
        if config.fine_silence and candidates:
            midpoint = (gap_start + gap_end) / 2
            chosen = min(candidates, key=lambda item: abs((item[0] + item[1]) / 2 - midpoint))
            boundaries.append((chosen[0] + chosen[1]) / 2)
        else:
            boundaries.append((gap_start + gap_end) / 2)
    result = []
    for index, span in enumerate(spans):
        lower = boundaries[index - 1] if index else 0.0
        upper = boundaries[index] if index < len(boundaries) else duration
        if span.job.contains_inline_vocal_event:
            padding = config.tagged_event_padding_ms / 1000
            # Non-lexical sighs/laughs have no reliable timestamp. Preserve
            # the whole safe neighborhood when it is small; at minimum keep
            # the configured wider padding.
            start = lower if span.first - lower <= padding * 3 else max(lower, span.first - padding)
            end = upper if upper - span.last <= padding * 3 else min(upper, span.last + padding)
            status = "NEEDS_REVIEW" if span.status == "NEEDS_REVIEW" else "REVIEW_RECOMMENDED"
        else:
            start = max(lower, span.first - config.pre_roll_ms / 1000)
            end = min(upper, span.last + config.post_roll_ms / 1000)
            status = span.status
        if end <= start or span.first < lower - .04 or span.last > upper + .04:
            raise AlignmentError(f"job {span.job.job_id} 没有安全切割区间")
        result.append((start, end, status))
    return result
