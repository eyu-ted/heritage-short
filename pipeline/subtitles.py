"""English subtitles from the timeline: at most 2 lines of ~40 characters per cue.

A long narration line is split into several cues at word boundaries, and its
spoken time is shared between them in proportion to their length.
"""
from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from functools import lru_cache

from .timeline import Slot

MAX_CHARS = 40
MAX_LINES = 2
MIN_CUE_S = 1.0
PUNCT_BONUS = 200  # prefer breaking a long line after , . ; : ! ? (in squared-char units)


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    lines: tuple[str, ...]


def _fits(text: str) -> bool:
    return len(textwrap.wrap(text, MAX_CHARS)) <= MAX_LINES


def lines_for(piece: str) -> tuple[str, ...]:
    """Wrap a cue into balanced lines ("One pot. Many cups. / No one was ever left out."),
    not a full first line and a one-word second line."""
    if len(piece) <= MAX_CHARS:
        return (piece,)
    for width in range(math.ceil(len(piece) / 2), MAX_CHARS + 1):
        wrapped = textwrap.wrap(piece, width)
        if len(wrapped) <= MAX_LINES:
            return tuple(wrapped)
    return tuple(textwrap.wrap(piece, MAX_CHARS))


def _greedy(words: list[str]) -> list[str]:
    chunks, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and not _fits(candidate):
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk(text: str) -> list[str]:
    """Split text into the fewest pieces that each fit MAX_LINES x MAX_CHARS, balanced in
    length and preferring breaks after punctuation.

    (A purely greedy split left orphans like "...grass on" / "the floor.", found when the
    my grandmother lines were added.)
    """
    words = text.split()
    greedy = _greedy(words)
    k, n = len(greedy), len(words)
    if k <= 1:
        return greedy
    target = len(text) / k

    @lru_cache(maxsize=None)
    def best(i: int, parts: int) -> tuple[float, tuple[int, ...]]:
        if parts == 1:
            piece = " ".join(words[i:])
            return ((len(piece) - target) ** 2, ()) if _fits(piece) else (math.inf, ())
        result: tuple[float, tuple[int, ...]] = (math.inf, ())
        for j in range(i + 1, n - parts + 2):
            piece = " ".join(words[i:j])
            if not _fits(piece):
                break
            cost = (len(piece) - target) ** 2 - (PUNCT_BONUS if piece[-1] in ",.;:!?" else 0)
            rest = best(j, parts - 1)
            if cost + rest[0] < result[0]:
                result = (cost + rest[0], (j, *rest[1]))
        return result

    cost, cuts = best(0, k)
    if math.isinf(cost):
        return greedy
    bounds = [0, *cuts, n]
    return [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]


def cues_for(slots: list[Slot]) -> list[Cue]:
    """Cues share the spoken time in proportion to their length, with a readable minimum,
    and always end exactly when the line ends."""
    cues: list[Cue] = []
    for slot in slots:
        if not slot.text_en.strip() or not slot.narration_s:
            continue
        pieces = chunk(slot.text_en)
        total_chars = sum(len(p) for p in pieces)
        shares = [max(MIN_CUE_S, slot.narration_s * len(p) / total_chars) for p in pieces]
        scale = slot.narration_s / sum(shares)
        t = slot.narration_start
        for piece, share in zip(pieces, shares):
            end = t + share * scale
            cues.append(Cue(round(t, 3), round(end, 3), lines_for(piece)))
            t = end
    return cues


def _stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [f"{i}\n{_stamp(c.start)} --> {_stamp(c.end)}\n" + "\n".join(c.lines)
              for i, c in enumerate(cues, start=1)]
    return "\n\n".join(blocks) + "\n"
