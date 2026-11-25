"""Stage 2 - keyframes: one square still per shot from Cloudflare FLUX.2 klein-4b.

  - Every prompt = shot prompt + reference descriptions + the fixed style block, so the
    look is described the same way every time.
  - Approved reference images (refs.py) are sent as klein's input_image_0..3, and the
    prompt says which image is which. A shot that needs a reference with no approved
    image is BLOCKED: the reference sheet comes before keyframes.
  - Square (1536x1536) with the subject centred: one master that crops cleanly to
    both 9:16 and 16:9.
  - Seeds do not reproduce images on Cloudflare (E2), so a retake is an explicit new
    version: bump `keyframe.take` in the storyboard. The previous take is kept.
"""
from __future__ import annotations

import io
from typing import Any

from PIL import Image

from .cache import Manifest, artifact_path
from .calls import logged_call
from .config import Paths, require_env
from .context import Context
from .hashing import hash_file
from .jobs import Job
from .providers.cloudflare import MODELS, Cloudflare
from .storyboard import shots_in_order

NAME = "keyframes"
EXT = "jpg"
PHASE = 4
REF_UPLOAD_MAX = 512  # klein's documented limit for input images (9B: < 512x512)


def _refs_for(sb: dict[str, Any], shot: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {r["id"]: r for r in sb["references"]}
    return [by_id[r] for r in shot["keyframe"]["refs"]]


def compose_prompt(sb: dict[str, Any], shot: dict[str, Any]) -> str:
    refs = _refs_for(sb, shot)
    parts = [shot["keyframe"]["prompt"].rstrip(".")]
    with_images = [r for r in refs if r.get("image")]
    if with_images:
        parts.append("Match the reference images exactly for: " + ", ".join(
            f"{r['id']} (image {n})" for n, r in enumerate(with_images, start=1)))
    parts += [r["description"].rstrip(".") for r in refs]
    parts.append(sb["style_block"].rstrip("."))
    return ". ".join(parts) + "."


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    paths = manifest.paths
    out = []
    for shot in shots_in_order(sb):
        refs = _refs_for(sb, shot)
        missing = [r["id"] for r in refs
                   if not r.get("image") or not paths.abs(r["image"]).exists()]
        # The hash of each reference FILE is part of the cache key: re-picking a reference
        # regenerates exactly the shots that use it.
        ref_hashes = {r["id"]: hash_file(paths.abs(r["image"])) for r in refs if r["id"] not in missing}
        inputs = {
            "model": sb["models"]["image"],
            "prompt": compose_prompt(sb, shot),
            "seed": shot["keyframe"]["seed"],
            "size": sb["render"]["keyframe_size"],
            "take": shot["keyframe"].get("take", 1),
            "refs": ref_hashes,
        }
        blocked = (f"reference(s) {missing} have no approved image "
                   f"(run `python -m pipeline refs`, then --pick)") if missing else None
        out.append(Job(NAME, shot["id"], EXT, inputs, blocked))
    return out


def _ref_bytes(paths: Paths, rel: str) -> bytes:
    img = Image.open(paths.abs(rel)).convert("RGB")
    img.thumbnail((REF_UPLOAD_MAX, REF_UPLOAD_MAX))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run(ctx: Context, todo: list[Job]) -> None:
    if not todo:
        return
    cf = Cloudflare(require_env("CLOUDFLARE_ACCOUNT_ID"), require_env("CLOUDFLARE_API_TOKEN"))
    shots = {s["id"]: s for s in ctx.sb["shots"]}
    for job in todo:
        i = job.inputs
        spec = MODELS[i["model"]]
        refs = [r for r in _refs_for(ctx.sb, shots[job.key]) if r.get("image")]
        kwargs: dict[str, Any] = {}
        if spec.seed:
            kwargs["seed"] = i["seed"]
        if spec.size:
            kwargs["width"], kwargs["height"] = i["size"]
        if refs and spec.max_refs:
            kwargs["refs"] = [_ref_bytes(ctx.paths, r["image"]) for r in refs[: spec.max_refs]]
        path = artifact_path(ctx.paths, job)
        data = logged_call(
            ctx.paths, lambda: cf.image(i["model"], i["prompt"], **kwargs),
            stage=NAME, provider="cloudflare", model=i["model"], shot_id=job.key, seed=i["seed"],
            params={"size": i["size"], "take": i["take"], "refs": [r["id"] for r in refs]},
            input_hash=job.hash, output=ctx.paths.rel(path),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        w, h = Image.open(path).size
        ctx.manifest.record(job, path, meta={"width": w, "height": h, "take": i["take"],
                                             "refs": [r["id"] for r in refs]})
        print(f"[keyframes] {job.key} (take {i['take']}) {w}x{h} -> {ctx.paths.rel(path)}")
