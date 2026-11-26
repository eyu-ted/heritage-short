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


LINE_PUNCT_BONUS = 12  # a break after punctuation may be up to this many chars less balanced


def lines_for(piece: str) -> tuple[str, ...]:
    """Wrap a cue into two balanced lines, preferring a break after punctuation:
    "One pot. Many cups. / No one was ever left out." rather than "... No / one was ...",
    and never a full first line with a one-word second line."""
    if len(piece) <= MAX_CHARS:
        return (piece,)
    words = piece.split()
    best: tuple[float, tuple[str, ...]] | None = None
    for i in range(1, len(words)):
        first, second = " ".join(words[:i]), " ".join(words[i:])
        if len(first) > MAX_CHARS or len(second) > MAX_CHARS:
            continue
        cost = abs(len(first) - len(second)) - (LINE_PUNCT_BONUS if first[-1] in ",.;:!?" else 0)
        if best is None or cost < best[0]:
            best = (cost, (first, second))
    return best[1] if best else tuple(textwrap.wrap(piece, MAX_CHARS))


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
    real script lines were added.)
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


def _ass_stamp(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def style_for(width: int, height: int) -> dict[str, int]:
    """Font and bottom margin in real pixels. Vertical video keeps text above the platform's
    buttons and caption area (the bottom ~20% of a phone feed)."""
    font = round(min(width * 0.046, height * 0.06))  # ~40 characters fit across the frame
    margin = round(height * (0.20 if height > width else 0.07))
    return {"font": font, "margin_v": margin, "outline": max(2, font // 14)}


def _plain(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")  # braces would start an ASS override tag


@dataclass(frozen=True)
class Card:
    """The end card: a main line and a smaller line, centred on black, fading in."""
    start: float
    end: float
    text: str
    subtitle: str = ""


def to_ass(cues: list[Cue], width: int, height: int, card: Card | None = None) -> str:
    """Subtitles for burning in. Unlike SRT (scaled from a fixed 288-px canvas, which made the
    vertical text huge and re-wrapped it into 3-4 lines), ASS is laid out in real pixels, and
    WrapStyle 2 keeps exactly the two-line breaks chosen above. The end card (if any) is drawn
    by the same renderer, so no font file path has to be passed to FFmpeg."""
    st = style_for(width, height)
    card_font = round(min(width, height) * 0.085)
    card_sub = round(card_font * 0.5)
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{st['font']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,"
        f"1,{st['outline']},0,2,{round(width * 0.05)},{round(width * 0.05)},{st['margin_v']},1",
        f"Style: Card,Arial,{card_font},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,"
        f"1,0,0,5,{round(width * 0.06)},{round(width * 0.06)},0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = [
        f"Dialogue: 0,{_ass_stamp(c.start)},{_ass_stamp(c.end)},Default,,0,0,0,,"
        + "\\N".join(_plain(line) for line in c.lines)
        for c in cues
    ]
    if card is not None:
        body = _plain(card.text)
        if card.subtitle:
            body += f"\\N{{\\fs{card_sub}\\b0\\alpha&H40&}}{_plain(card.subtitle)}"
        events.append(f"Dialogue: 1,{_ass_stamp(card.start)},{_ass_stamp(card.end)},Card,,0,0,0,,"
                      f"{{\\fad(700,0)}}{body}")
    return "\n".join(head + events) + "\n"
