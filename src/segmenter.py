"""Pure duration/silence based segment planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Segment:
    """A half-open audio segment measured in seconds."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def calculate_segments(
    duration: float,
    silence_intervals: Iterable[tuple[float, float]],
    *,
    target: float = 180.0,
    preferred_min: float = 120.0,
    preferred_max: float = 240.0,
    short_tail: float = 30.0,
) -> list[Segment]:
    """Calculate non-overlapping segments without reading audio data.

    Silence interval midpoints within the preferred window are preferred. If
    none exist, a hard cut is made at the target duration. A final short tail
    is merged into the preceding segment.
    """
    if duration < 0:
        raise ValueError("duration must not be negative")
    if duration == 0:
        return []
    if not 0 < preferred_min <= target <= preferred_max:
        raise ValueError("expected 0 < preferred_min <= target <= preferred_max")
    if short_tail < 0:
        raise ValueError("short_tail must not be negative")

    candidates = sorted(
        {
            max(0.0, min(duration, (float(start) + float(end)) / 2.0))
            for start, end in silence_intervals
            if end >= start
        }
    )
    boundaries = [0.0]
    current = 0.0
    epsilon = 1e-6

    while duration - current > preferred_max + epsilon:
        low = current + preferred_min
        high = min(current + preferred_max, duration)
        desired = current + target
        eligible = [point for point in candidates if low <= point <= high]
        cut = min(eligible, key=lambda point: (abs(point - desired), point)) if eligible else desired
        if cut <= current + epsilon:
            break
        boundaries.append(min(cut, duration))
        current = cut

    boundaries.append(duration)
    segments = [
        Segment(start, end)
        for start, end in zip(boundaries, boundaries[1:])
        if end - start > epsilon
    ]

    if len(segments) >= 2 and segments[-1].duration < short_tail:
        segments[-2:] = [Segment(segments[-2].start, segments[-1].end)]
    return segments
