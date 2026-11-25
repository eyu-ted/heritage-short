"""Stage 3 - shots: give each keyframe motion.

Two backends, chosen per shot in the storyboard:
  wan       image-to-video clip made on Kaggle (Wan 2.2 TI2V-5B), ingested here
  kenburns  slow pan/zoom over the still, rendered locally with FFmpeg

The cache key includes the HASH OF THE KEYFRAME FILE, so a new keyframe
automatically invalidates its shot, and only its shot.
"""
from __future__ import annotations

from typing import Any

from .cache import Manifest
from .context import Context
from .hashing import hash_file
from .jobs import Job
from .storyboard import shot_duration, shots_in_order

NAME = "shots"
EXT = "mp4"
PHASE = 4


def narration_seconds(manifest: Manifest, shot_id: str) -> float | None:
    entry = manifest.entry("narration", shot_id)
    if entry and manifest.artifact("narration", shot_id):
        return entry.get("meta", {}).get("duration_s")
    return None


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    out = []
    for shot in shots_in_order(sb):
        motion = shot["motion"]
        keyframe = manifest.artifact("keyframes", shot["id"])
        keyframe_hash = hash_file(keyframe) if keyframe else None
        blocked = None if keyframe_hash else "needs its keyframe first"

        if motion["backend"] == "wan":
            inputs = {
                "backend": "wan",
                "model": sb["models"]["video"],
                "keyframe": keyframe_hash,
                "prompt": motion["prompt"],
                "seed": motion["seed"],
                "resolution": sb["render"]["video_resolution"],
                "fps": sb["render"]["fps"],
            }
        else:
            seconds = narration_seconds(manifest, shot["id"])
            if blocked is None and seconds is None:
                blocked = "needs narration timing first"
            inputs = {
                "backend": "kenburns",
                "keyframe": keyframe_hash,
                "zoom": motion["kenburns"]["zoom"],
                "pan": motion["kenburns"]["pan"],
                "duration_s": shot_duration(sb, shot, seconds),
                "fps": sb["render"]["fps"],
            }
        out.append(Job(NAME, shot["id"], EXT, inputs, blocked))
    return out


def run(ctx: Context, todo: list[Job]) -> None:
    raise NotImplementedError(f"the {NAME} stage is built in Phase {PHASE} (Ken Burns) and Phase 6 (Wan)")
