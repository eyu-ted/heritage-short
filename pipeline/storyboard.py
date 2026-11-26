"""Load and validate storyboard.json.

Two layers of checking:
  1. JSON Schema (schema/storyboard.schema.json): structure, types, ranges.
  2. Semantic checks here: things a schema cannot express (unique ids,
     contiguous order, references that exist, total duration in range).

`check_ready(sb, stage)` is a third, softer layer: is the storyboard complete
enough for a given stage to run (e.g. Amharic narration filled in)?
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .config import Paths


class StoryboardError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("storyboard.json is invalid:\n  - " + "\n  - ".join(errors))


def _schema(paths: Paths) -> dict[str, Any]:
    with open(paths.schema, encoding="utf-8") as fh:
        return json.load(fh)


def _schema_errors(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{where}: {err.message}")
    return errors


def _semantic_errors(sb: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    shots = sb["shots"]

    ids = [s["id"] for s in shots]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"shots: duplicate ids {dupes}")

    orders = sorted(s["order"] for s in shots)
    if orders != list(range(1, len(shots) + 1)):
        errors.append(f"shots: order must be 1..{len(shots)} with no gaps, got {orders}")

    ref_ids = [r["id"] for r in sb["references"]]
    if len(ref_ids) != len(set(ref_ids)):
        errors.append("references: duplicate ids")
    for shot in shots:
        missing = [r for r in shot["keyframe"]["refs"] if r not in ref_ids]
        if missing:
            errors.append(f"shots/{shot['id']}: unknown reference ids {missing}")

    cue_ids = [c["id"] for c in sb["music"]["cues"]]
    if len(cue_ids) != len(set(cue_ids)):
        errors.append("music/cues: duplicate ids")
    chosen = sb["music"]["chosen"]
    if chosen is not None and chosen not in music_candidates(sb):
        errors.append(f"music/chosen: {chosen!r} is not one of {music_candidates(sb)}")

    total = planned_duration(sb)
    lo, hi = sb["project"]["target_duration_s"]["min"], sb["project"]["target_duration_s"]["max"]
    if not lo <= total <= hi:
        errors.append(f"planned duration {total:.1f}s is outside {lo}-{hi}s")
    return errors


def validate(data: dict[str, Any], paths: Paths) -> list[str]:
    """Return a list of problems (empty list = valid)."""
    errors = _schema_errors(data, _schema(paths))
    if errors:
        return errors  # semantic checks assume the structure is right
    return _semantic_errors(data)


def load(paths: Paths, path: Path | None = None) -> dict[str, Any]:
    path = path or paths.storyboard
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    errors = validate(data, paths)
    if errors:
        raise StoryboardError(errors)
    return data


# ---- helpers used by the stages -------------------------------------------

def shots_in_order(sb: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(sb["shots"], key=lambda s: s["order"])


def get_shot(sb: dict[str, Any], shot_id: str) -> dict[str, Any]:
    for shot in sb["shots"]:
        if shot["id"] == shot_id:
            return shot
    raise KeyError(f"No shot {shot_id!r} in storyboard")


def music_candidates(sb: dict[str, Any]) -> list[str]:
    return [f"{c['id']}-seed{s}" for c in sb["music"]["cues"] for s in c["seeds"]]


def shot_duration(sb: dict[str, Any], shot: dict[str, Any], narration_s: float | None) -> float:
    """The narration sets the pace: a shot lasts its line plus a breath, never less than its minimum."""
    base = float(shot["min_duration_s"])
    if narration_s is None:
        return base
    return round(max(base, narration_s + sb["render"]["narration_pad_s"]), 3)


def planned_duration(sb: dict[str, Any], narration_s: dict[str, float] | None = None) -> float:
    narration_s = narration_s or {}
    shots = sum(shot_duration(sb, s, narration_s.get(s["id"])) for s in sb["shots"])
    return shots + float(sb["endcard"]["duration_s"])


def check_ready(sb: dict[str, Any], stage: str) -> list[str]:
    """What is still missing before `stage` can run for real."""
    problems: list[str] = []
    if stage in ("narration", "assemble"):
        empty = [s["id"] for s in shots_in_order(sb) if not s["narration"]["am"].strip()]
        if empty:
            problems.append(f"Amharic narration is empty for {empty} (step S3.2)")
    if stage == "assemble" and sb["music"]["chosen"] is None:
        problems.append("no music candidate chosen yet (step S5.2); the placeholder bed will be used")
    return problems
