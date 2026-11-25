"""When does each shot start, and when does its narration line play?

The narration sets the pace (professionals cut picture to the voice): each shot
lasts its line plus a breath, never less than its minimum. The radio cut and the
final edit share this one timeline, so what testers hear is what the film does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .storyboard import shot_duration, shots_in_order


@dataclass(frozen=True)
class Slot:
    shot_id: str
    start: float
    duration: float
    narration_start: float
    narration_s: float | None
    text_en: str

    @property
    def end(self) -> float:
        return self.start + self.duration


def build(sb: dict[str, Any], narration_s: dict[str, float]) -> tuple[list[Slot], float]:
    """Return the shot slots and the total film length (including the end card)."""
    offset = float(sb["mix"]["narration_offset_s"])
    slots, t = [], 0.0
    for shot in shots_in_order(sb):
        spoken = narration_s.get(shot["id"])
        length = shot_duration(sb, shot, spoken)
        slots.append(Slot(shot["id"], round(t, 3), length, round(t + offset, 3), spoken, shot["narration"]["en"]))
        t += length
    return slots, round(t + float(sb["endcard"]["duration_s"]), 3)
