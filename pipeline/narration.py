"""Stage 1 - narration: one Amharic WAV per shot from Gemini TTS.

Cache key: model, language, text, voice, style. Change one line -> one new WAV.
"""
from __future__ import annotations

from typing import Any

from .cache import Manifest
from .context import Context
from .jobs import Job
from .storyboard import shots_in_order

NAME = "narration"
EXT = "wav"
PHASE = 3


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    defaults = sb["narration_defaults"]
    out = []
    for shot in shots_in_order(sb):
        n = shot["narration"]
        text = n["am"].strip()
        inputs = {
            "model": sb["models"]["tts"],
            "language": sb["project"]["language"],
            "text": text,
            "voice": n.get("voice") or defaults["voice"],
            "style": n.get("style") or defaults["style"],
        }
        blocked = None if text else "Amharic line is empty (step S3.2)"
        out.append(Job(NAME, shot["id"], EXT, inputs, blocked))
    return out


def run(ctx: Context, todo: list[Job]) -> None:
    raise NotImplementedError(f"the {NAME} stage is built in Phase {PHASE}")
