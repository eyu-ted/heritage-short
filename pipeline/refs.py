"""Pre-production: the reference sheet (look development), generated BEFORE any keyframe.

Why: in the smoke test (EXPERIMENTS E3) the model drew a teapot and an urn instead of a
jebena, and cups with handles. Words alone did not pin the props, and seeds do not
reproduce images on Cloudflare (E2). So each recurring element (the jebena, the sini
cups, the elder seen from behind) gets a few generated options; a human picks one;
the picked image is passed to every keyframe that shows that element.

  python -m pipeline refs                      # make missing options (default 4 per reference)
  python -m pipeline refs --pick jebena=2      # approve option 2 as the jebena reference
"""
from __future__ import annotations

import json
from typing import Any

from .cache import Manifest, artifact_path
from .calls import logged_call
from .config import require_env
from .context import Context
from .jobs import Job
from .providers.cloudflare import MODELS, Cloudflare

NAME = "refs"
EXT = "jpg"
SIZE = (1024, 1024)
SHEET = ("Shown alone and complete, centred on a plain warm cream background, evenly lit, "
         "as a clean reference image for an illustrator")


def ref_prompt(sb: dict[str, Any], ref: dict[str, Any]) -> str:
    return f"{ref['description'].rstrip('.')}. {SHEET}. {sb['style_block']}"


def jobs(sb: dict[str, Any], manifest: Manifest, options: int = 4) -> list[Job]:
    out = []
    for ref in sb["references"]:
        for k in range(1, options + 1):
            inputs = {"model": sb["models"]["image"], "prompt": ref_prompt(sb, ref),
                      "size": list(SIZE), "seed": ref.get("seed", 0) + k, "option": k}
            out.append(Job(NAME, f"{ref['id']}-opt{k}", EXT, inputs))
    return out


def run(ctx: Context, todo: list[Job]) -> None:
    if not todo:
        return
    cf = Cloudflare(require_env("CLOUDFLARE_ACCOUNT_ID"), require_env("CLOUDFLARE_API_TOKEN"))
    for job in todo:
        i = job.inputs
        spec = MODELS[i["model"]]
        kwargs = {}
        if spec.seed:
            kwargs["seed"] = i["seed"]
        if spec.size:
            kwargs["width"], kwargs["height"] = i["size"]
        path = artifact_path(ctx.paths, job)
        data = logged_call(
            ctx.paths, lambda: cf.image(i["model"], i["prompt"], **kwargs),
            stage=NAME, provider="cloudflare", model=i["model"], shot_id=job.key, seed=i["seed"],
            params={"size": i["size"], "option": i["option"]}, input_hash=job.hash,
            output=ctx.paths.rel(path),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        ctx.manifest.record(job, path, meta={"option": i["option"]})
        print(f"[refs] {job.key} -> {ctx.paths.rel(path)}")


def pick(ctx: Context, choice: str) -> str:
    """Approve an option: 'jebena=2' sets references[jebena].image to that file."""
    try:
        ref_id, number = choice.split("=")
        key = f"{ref_id}-opt{int(number)}"
    except ValueError as exc:
        raise ValueError("use --pick <reference>=<option number>, e.g. --pick jebena=2") from exc
    path = ctx.manifest.artifact(NAME, key)
    if not path:
        raise ValueError(f"no generated option {key}; run `python -m pipeline refs` first")
    ref = next((r for r in ctx.sb["references"] if r["id"] == ref_id), None)
    if ref is None:
        raise ValueError(f"unknown reference {ref_id!r}")
    ref["image"] = ctx.paths.rel(path)
    ctx.paths.storyboard.write_text(json.dumps(ctx.sb, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
    return ref["image"]
