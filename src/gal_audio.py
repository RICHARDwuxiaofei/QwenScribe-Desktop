"""PCM WAV inspection, fine silence detection and sample accurate slicing."""
from __future__ import annotations

import audioop
import math
from pathlib import Path
import wave


class AudioError(ValueError):
    pass


def inspect_wav(path: Path) -> tuple[int, int, int, int, float]:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getcomptype() != "NONE" or wav.getsampwidth() not in (1, 2, 3, 4):
                raise AudioError("仅支持 PCM WAV master；请先无损转换")
            rate, channels, width, frames = wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()
            if rate <= 0 or channels <= 0 or frames <= 0:
                raise AudioError("WAV 无效或为空")
            return rate, channels, width, frames, frames / rate
    except (wave.Error, EOFError, OSError) as error:
        raise AudioError(f"WAV 损坏或无法读取：{error}") from error


def find_silences(path: Path, threshold_db: float, minimum_ms: int) -> list[tuple[float, float]]:
    rate, channels, width, _, duration = inspect_wav(path)
    step = max(1, round(rate * .01))
    threshold = (2 ** (width * 8 - 1) - 1) * 10 ** (threshold_db / 20)
    regions: list[tuple[float, float]] = []
    started: float | None = None
    with wave.open(str(path), "rb") as wav:
        frame = 0
        while data := wav.readframes(step):
            rms = audioop.rms(data, width)
            silent = rms <= threshold
            now = frame / rate
            if silent and started is None:
                started = now
            if not silent and started is not None:
                if (now - started) * 1000 >= minimum_ms:
                    regions.append((started, now))
                started = None
            frame += len(data) // (width * channels)
    if started is not None and (duration - started) * 1000 >= minimum_ms:
        regions.append((started, duration))
    return regions


def slice_wav(source: Path, destination: Path, start: float, end: float) -> tuple[float, int]:
    rate, _, _, frames, _ = inspect_wav(source)
    first = max(0, min(frames, round(start * rate)))
    last = max(first, min(frames, round(end * rate)))
    if last <= first:
        raise AudioError("切割区间为空")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    with wave.open(str(source), "rb") as src, wave.open(str(temporary), "wb") as dst:
        dst.setparams(src.getparams())
        src.setpos(first)
        remaining = last - first
        while remaining:
            block = src.readframes(min(65536, remaining))
            if not block:
                raise AudioError("WAV 提前结束")
            dst.writeframesraw(block)
            remaining -= len(block) // (src.getnchannels() * src.getsampwidth())
    temporary.replace(destination)
    return (last - first) / rate, rate
