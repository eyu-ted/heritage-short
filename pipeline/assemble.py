"""Stage 5 - assemble: the edit, done entirely with FFmpeg (deterministic, no AI).

The cache key is built from the hashes of every input file plus the mix,
subtitle and end-card settings, so the film is only re-rendered when
something it is made of actually changed.
"""
from __future__ import annotations

from typing import Any

from .cache import Manifest
from .context import Context
from .hashing import hash_file
from .jobs import Job
from .storyboard import shots_in_order

NAME = "assemble"
EXT = "mp4"
PHASE = 7


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    parts: dict[str, str] = {}
    missing: list[str] = []
    for shot in shots_in_order(sb):
        for stage in ("narration", "shots"):
            path = manifest.artifact(stage, shot["id"])
            if path:
                parts[f"{stage}/{shot['id']}"] = hash_file(path)
            else:
                missing.append(f"{stage}/{shot['id']}")
    chosen = sb["music"]["chosen"]
    music_path = manifest.artifact("music", chosen) if chosen else None
    if music_path:
        parts["music"] = hash_file(music_path)
    else:
        missing.append("music (none chosen)" if not chosen else f"music/{chosen}")

    inputs = {
        "parts": parts,
        "subtitles": [s["narration"]["en"] for s in shots_in_order(sb)],
        "mix": sb["mix"],
        "endcard": sb["endcard"],
        "outputs": sb["project"]["outputs"],
        "reframe": sb["project"]["reframe"],
        "fps": sb["render"]["fps"],
        "crossfade_s": sb["render"]["crossfade_s"],
    }
    blocked = None
    if missing:
        blocked = f"waiting for {len(missing)} inputs (e.g. {', '.join(missing[:3])})"
    return [Job(NAME, "film", EXT, inputs, blocked)]


def run(ctx: Context, todo: list[Job]) -> None:
    raise NotImplementedError(f"the {NAME} stage is built in Phase {PHASE}")
