"""Stage 4 - music: score candidates from ACE-Step 1.5 (made on Kaggle, ingested here).

One job per (cue, seed). Kaggle notebook: `python -m pipeline export music`, run it, then
`python -m pipeline ingest music --from <download>`. A human listens to the candidates under
the narration (`python -m pipeline radio --music score-seed22`) and approves one:
`python -m pipeline music --pick score-seed22` (written to storyboard music.chosen).

The model is run WITHOUT its language model ("thinking" off), so the tempo, key and
length are exactly the ones in the storyboard instead of being re-guessed by the LM.
"""
from __future__ import annotations

import json
from typing import Any

from .cache import Manifest
from .context import Context
from .jobs import Job, NotReadyError
from .storyboard import music_candidates

NAME = "music"
EXT = "wav"
PHASE = 5
# Generation settings (part of every job's hash). Turbo: 8 steps, shift 3 (the docs' advice).
ACE = {"variant": "acestep-v15-turbo", "repo_tag": "v0.1.8", "steps": 8, "shift": 3.0, "thinking": False}


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    out = []
    for cue in sb["music"]["cues"]:
        for seed in cue["seeds"]:
            inputs = {
                "model": sb["models"]["music"],
                "caption": cue["caption"],
                "bpm": cue["bpm"],
                "keyscale": cue.get("key"),  # musical key; "key" is the job's name
                "duration_s": cue["duration_s"],
                "instrumental": cue["instrumental"],
                "seed": seed,
                **ACE,
            }
            out.append(Job(NAME, f"{cue['id']}-seed{seed}", EXT, inputs))
    return out


def run(ctx: Context, todo: list[Job]) -> None:
    if todo:
        raise NotReadyError(
            f"music: {len(todo)} candidate(s) not made yet {[j.key for j in todo]}. They are made on Kaggle: "
            "`python -m pipeline export music`, run the notebook, then "
            "`python -m pipeline ingest music --from <download>`")


def pick(ctx: Context, key: str) -> str:
    if key not in music_candidates(ctx.sb):
        raise ValueError(f"unknown music candidate {key!r}; choose one of {music_candidates(ctx.sb)}")
    job = next(j for j in jobs(ctx.sb, ctx.manifest) if j.key == key)
    if not ctx.manifest.is_fresh(job):
        raise ValueError(f"{key} has not been ingested for the current inputs; run `python -m pipeline ingest music`")
    ctx.sb["music"]["chosen"] = key
    ctx.paths.storyboard.write_text(json.dumps(ctx.sb, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
    return key


def candidate_path(ctx: Context, key: str):
    """The ingested WAV for a candidate made from the current inputs, or None."""
    job = next((j for j in jobs(ctx.sb, ctx.manifest) if j.key == key), None)
    if job is None or not ctx.manifest.is_fresh(job):
        return None
    return ctx.manifest.artifact(NAME, key)
