"""Stage 4 - music: score candidates from ACE-Step 1.5 (run on Kaggle, ingested here).

One job per (cue, seed). The chosen candidate is named in storyboard music.chosen.
"""
from __future__ import annotations

from typing import Any

from .cache import Manifest
from .context import Context
from .jobs import Job

NAME = "music"
EXT = "wav"
PHASE = 5


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    out = []
    for cue in sb["music"]["cues"]:
        for seed in cue["seeds"]:
            inputs = {
                "model": sb["models"]["music"],
                "caption": cue["caption"],
                "bpm": cue["bpm"],
                "key": cue.get("key"),
                "duration_s": cue["duration_s"],
                "instrumental": cue["instrumental"],
                "seed": seed,
            }
            out.append(Job(NAME, f"{cue['id']}-seed{seed}", EXT, inputs))
    return out


def run(ctx: Context, todo: list[Job]) -> None:
    raise NotImplementedError(f"the {NAME} stage is built in Phase {PHASE}")
