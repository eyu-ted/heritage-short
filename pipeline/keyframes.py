"""Stage 2 - keyframes: one still per shot from Cloudflare FLUX.

Every prompt = shot prompt + reference descriptions + the fixed style block,
so the look is described the same way every time (the main cause of drift is
re-describing things differently).
"""
from __future__ import annotations

from typing import Any

from .cache import Manifest
from .context import Context
from .jobs import Job
from .storyboard import shots_in_order

NAME = "keyframes"
EXT = "png"
PHASE = 4


def compose_prompt(sb: dict[str, Any], shot: dict[str, Any]) -> str:
    refs = {r["id"]: r["description"] for r in sb["references"]}
    parts = [shot["keyframe"]["prompt"].rstrip(".")]
    parts += [refs[r].rstrip(".") for r in shot["keyframe"]["refs"]]
    parts.append(sb["style_block"].rstrip("."))
    return ". ".join(parts) + "."


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    out = []
    for shot in shots_in_order(sb):
        inputs = {
            "model": sb["models"]["image"],
            "prompt": compose_prompt(sb, shot),
            "seed": shot["keyframe"]["seed"],
            "size": sb["render"]["keyframe_size"],
            "steps": sb["render"]["image_steps"],
        }
        out.append(Job(NAME, shot["id"], EXT, inputs))
    return out


def run(ctx: Context, todo: list[Job]) -> None:
    raise NotImplementedError(f"the {NAME} stage is built in Phase {PHASE}")
