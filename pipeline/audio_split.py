"""Cut one long narration recording into per-line pieces at its longest silences.

Why: the free tier allows only 10 TTS requests per model per day (FAILURES F8).
Asking for all lines in ONE request, separated by long pauses, then cutting at the
N-1 longest silences, turns 10 requests into 1.

Safety: the cut is only accepted if every piece's length is plausible for its line
(proportional to the number of characters). Otherwise SplitError is raised and the
caller can fall back to one request per line. Pure Python, deterministic, testable.
"""
from __future__ import annotations

import array
import math
from dataclasses import dataclass

WINDOW_S = 0.02  # analysis window
MIN_SILENCE_S = 0.25  # shorter gaps are breaths inside a line, not line breaks
EDGE_PAD_S = 0.08  # keep a little room before/after each piece
RATIO_RANGE = (0.35, 2.8)  # accepted piece length vs its expected share


class SplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Silence:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def middle(self) -> float:
        return (self.start + self.end) / 2


def _samples(pcm: bytes) -> array.array:
    data = array.array("h")
    data.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    return data


def _rms_windows(samples: array.array, rate: int) -> list[float]:
    step = max(1, int(rate * WINDOW_S))
    out = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        out.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)) if chunk else 0.0)
    return out


def find_silences(pcm: bytes, rate: int) -> list[Silence]:
    """Silent stretches longer than MIN_SILENCE_S, threshold relative to the loudest window."""
    samples = _samples(pcm)
    rms = _rms_windows(samples, rate)
    if not rms or max(rms) == 0:
        return []
    threshold = max(rms) * 0.04
    silences, run_start = [], None
    for i, value in enumerate(rms + [math.inf]):  # sentinel closes a trailing run
        if value < threshold and run_start is None:
            run_start = i
        elif value >= threshold and run_start is not None:
            start, end = run_start * WINDOW_S, i * WINDOW_S
            if end - start >= MIN_SILENCE_S:
                silences.append(Silence(round(start, 3), round(min(end, len(samples) / rate), 3)))
            run_start = None
    return silences


def split(pcm: bytes, rate: int, texts: list[str]) -> list[bytes]:
    """Cut `pcm` into len(texts) pieces at the longest interior silences."""
    n = len(texts)
    total = len(pcm) / 2 / rate
    if n == 1:
        return [pcm]
    silences = find_silences(pcm, rate)
    # interior gaps only: not the lead-in or the tail
    interior = [s for s in silences if s.start > EDGE_PAD_S and s.end < total - EDGE_PAD_S]
    if len(interior) < n - 1:
        raise SplitError(f"found {len(interior)} pauses, need {n - 1} to cut {n} lines")
    cuts = sorted(s.middle for s in sorted(interior, key=lambda s: s.length, reverse=True)[: n - 1])

    bounds = [0.0, *cuts, total]
    pieces = []
    for a, b in zip(bounds, bounds[1:]):
        start = max(0, int(a * rate)) * 2
        end = min(len(pcm), int(b * rate) * 2)
        pieces.append(_trim(pcm[start:end], rate))

    _check_plausible(pieces, rate, texts)
    return pieces


def _trim(pcm: bytes, rate: int) -> bytes:
    """Remove leading/trailing silence, keeping EDGE_PAD_S on each side."""
    samples = _samples(pcm)
    rms = _rms_windows(samples, rate)
    if not rms or max(rms) == 0:
        return pcm
    threshold = max(rms) * 0.04
    loud = [i for i, v in enumerate(rms) if v >= threshold]
    step = int(rate * WINDOW_S)
    pad = int(rate * EDGE_PAD_S)
    first = max(0, loud[0] * step - pad)
    last = min(len(samples), (loud[-1] + 1) * step + pad)
    return samples[first:last].tobytes()


def _check_plausible(pieces: list[bytes], rate: int, texts: list[str]) -> None:
    durations = [len(p) / 2 / rate for p in pieces]
    chars = [max(1, len(t)) for t in texts]
    spoken, total_chars = sum(durations), sum(chars)
    for i, (d, c) in enumerate(zip(durations, chars)):
        expected = spoken * c / total_chars
        ratio = d / expected if expected else 0
        if not RATIO_RANGE[0] <= ratio <= RATIO_RANGE[1]:
            raise SplitError(
                f"piece {i + 1} is {d:.2f}s but its line suggests ~{expected:.2f}s "
                f"(ratio {ratio:.2f}); the pauses probably did not fall between lines")
