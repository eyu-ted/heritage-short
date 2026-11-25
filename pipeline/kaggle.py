"""The Kaggle hand-off: the two GPU stages (Wan clips, ACE-Step music) run in Kaggle notebooks.

  python -m pipeline export wan [--shot s07]     # -> kaggle/build/wan_shots.ipynb
  python -m pipeline export music                # -> kaggle/build/ace_step_music.ipynb
  (upload the notebook to Kaggle, GPU + internet on, "Save & Run All"; download its output)
  python -m pipeline ingest wan --from <download folder or zip>
  python -m pipeline ingest music --from <download folder or zip>

Export writes the jobs that are NOT cached yet INTO the notebook (prompts, seeds, settings,
and for Wan the keyframe itself, resized to the generation size), so nothing else has to be
uploaded. Every output the notebook writes has a JSON sidecar with the job's hash.

Ingest trusts nothing: it accepts a file only if its hash is the hash the CURRENT storyboard
gives that job (so a clip made from an old keyframe or prompt is refused as stale), the file
exists and FFmpeg can read it. Accepted files are copied into outputs/, recorded in the
manifest, and logged to runs.jsonl with the GPU time the notebook measured. Errors the
notebook recorded are logged too.

Semi-manual on purpose: free Kaggle GPUs are a notebook product, not an API we can call per
job. The hash handshake is what keeps the manual step safe.
"""
from __future__ import annotations

import base64
import io
import json
import os
import pprint
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import ffmpeg, music, shots
from .cache import Manifest, artifact_path
from .config import ROOT
from .context import Context
from .jobs import Job
from .runlog import log_event


@dataclass(frozen=True)
class Target:
    name: str
    notebook: str  # source in notebooks/ (percent format), built into kaggle/build/<stem>.ipynb
    jobs: Callable[[dict[str, Any], Manifest], list[Job]]
    shot_based: bool


TARGETS = {
    "wan": Target("wan", "wan_shots.py", shots.clip_jobs, True),
    "music": Target("music", "ace_step_music.py", music.jobs, False),
}
JOBS_LINE = "JOBS = None"


def _target(name: str | None) -> Target:
    if name not in TARGETS:
        raise ValueError(f"choose what to export/ingest: {' or '.join(TARGETS)} (got {name!r})")
    return TARGETS[name]


# ---- export --------------------------------------------------------------------------

def _payload(ctx: Context, job: Job) -> dict[str, Any]:
    clash = {"key", "hash", "ext"} & set(job.inputs)
    if clash:
        raise ValueError(f"job inputs may not use the reserved names {sorted(clash)}")
    item = {"key": job.key, "hash": job.hash, "ext": job.ext, **job.inputs}
    if job.stage == shots.CLIP_STAGE:
        from PIL import Image

        size = job.inputs["size"]
        img = Image.open(ctx.manifest.artifact("keyframes", job.key)).convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        item["image_b64"] = base64.b64encode(buf.getvalue()).decode("ascii")
    return item


def notebook_from_percent(source: str, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn a percent-format script (# %% cells) into .ipynb JSON, with the jobs filled in."""
    cells: list[dict[str, Any]] = []
    kind, lines = None, []

    def flush():
        if kind is None:
            return
        body = "\n".join(lines).strip("\n")
        if kind == "markdown":
            body = "\n".join(re.sub(r"^# ?", "", ln) for ln in body.splitlines())
            cells.append({"cell_type": "markdown", "metadata": {}, "source": body.splitlines(keepends=True)})
        else:
            if body.lstrip().startswith(JOBS_LINE):
                literal = pprint.pformat(jobs, width=110, sort_dicts=False)
                body = body.replace(JOBS_LINE, f"JOBS = {literal}", 1)
            cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                          "source": body.splitlines(keepends=True)})

    for line in source.splitlines():
        m = re.match(r"^# %%(.*)$", line)
        if m:
            flush()
            kind, lines = ("markdown" if "[markdown]" in m.group(1) else "code"), []
        elif kind is not None:
            lines.append(line)
    flush()
    return {"cells": cells, "nbformat": 4, "nbformat_minor": 4,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python"}}}


def export(ctx: Context, name: str) -> Path | None:
    target = _target(name)
    all_jobs = target.jobs(ctx.sb, ctx.manifest)
    if target.shot_based and ctx.shot_ids:
        all_jobs = [j for j in all_jobs if j.key in ctx.shot_ids]
    blocked = [j for j in all_jobs if j.blocked]
    todo = [j for j in all_jobs if not j.blocked and (ctx.force or not ctx.manifest.is_fresh(j))]
    for j in blocked:
        print(f"[export {name}] {j.key}: blocked ({j.blocked})")
    print(f"[export {name}] {len(all_jobs) - len(todo) - len(blocked)} already ingested, "
          f"{len(todo)} to make, {len(blocked)} blocked")
    if not todo:
        return None

    payload = [_payload(ctx, j) for j in todo]
    src = ROOT / "notebooks" / target.notebook  # notebook sources are code, shipped with the package
    nb = notebook_from_percent(src.read_text(encoding="utf-8"), payload)
    out_dir = ctx.paths.root / "kaggle" / "build" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{Path(target.notebook).stem}.ipynb"
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    readable = [{k: v for k, v in item.items() if k != "image_b64"} for item in payload]
    (out_dir / "jobs.json").write_text(json.dumps({"jobs": readable}, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    (out_dir / "kernel-metadata.json").write_text(json.dumps(kernel_metadata(name, out.name), indent=2) + "\n",
                                                  encoding="utf-8")
    for item in readable:
        print(f"  {item['key']:<14} {item['hash']}")
    print(f"[export {name}] notebook: {ctx.paths.rel(out)}  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"  upload it on kaggle.com, or push it: kaggle kernels push -p {ctx.paths.rel(out_dir)}")
    return out


def kernel_metadata(name: str, code_file: str) -> dict[str, Any]:
    """For `kaggle kernels push`: a PRIVATE notebook on a T4 x2 GPU with internet (to download weights)."""
    user = os.environ.get("KAGGLE_USERNAME", "").strip() or "YOUR-KAGGLE-USERNAME"
    return {"id": f"{user}/buna-{name}", "title": f"buna-{name}", "code_file": code_file,
            "language": "python", "kernel_type": "notebook", "is_private": True,
            "enable_gpu": True, "enable_tpu": False, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": []}


# ---- ingest --------------------------------------------------------------------------

def _open_source(source: Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    if source.is_dir():
        return source, None
    if source.suffix.lower() == ".zip":
        tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(source) as zf:
            for member in zf.namelist():  # refuse path tricks in a downloaded archive
                if member.startswith(("/", "\\")) or ".." in Path(member).parts:
                    raise ValueError(f"unsafe path in zip: {member}")
            zf.extractall(tmp.name)
        return Path(tmp.name), tmp
    raise ValueError(f"--from must be a folder or a .zip, got {source}")


def _sidecars(folder: Path) -> list[tuple[Path, dict[str, Any]]]:
    found = []
    for path in sorted(folder.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and {"key", "hash", "status"} <= set(data):
            found.append((path, data))
    return found


def ingest(ctx: Context, name: str, source: Path) -> dict[str, list[str]]:
    target = _target(name)
    jobs = {j.key: j for j in target.jobs(ctx.sb, ctx.manifest)}
    folder, tmp = _open_source(Path(source))
    report: dict[str, list[str]] = {"ingested": [], "already": [], "stale": [], "failed": [], "unknown": []}
    try:
        sidecars = _sidecars(folder)
        if not sidecars:
            raise ValueError(f"no notebook outputs (sidecar .json files) found in {source}")
        for side_path, side in sidecars:
            key = side["key"]
            job = jobs.get(key)
            if job is None:
                report["unknown"].append(key)
                continue
            if side["hash"] != job.hash:
                report["stale"].append(key)
                print(f"[ingest {name}] {key}: STALE, made from older inputs ({side['hash']} != {job.hash}); skipped")
                continue
            common = dict(stage=job.stage, shot_id=key, provider="kaggle", model=job.inputs.get("model"),
                          seed=job.inputs.get("seed"), input_hash=job.hash,
                          params=side.get("settings"), latency_ms=_ms(side.get("seconds")),
                          gpu_minutes=_minutes(side.get("seconds")), note=side.get("gpu"))
            if side["status"] != "ok":
                report["failed"].append(key)
                log_event(ctx.paths.runs_log, status="error", error=str(side.get("error"))[:2000], **common)
                print(f"[ingest {name}] {key}: the notebook reported an error: {str(side.get('error'))[:200]}")
                continue
            if ctx.manifest.is_fresh(job) and not ctx.force:
                report["already"].append(key)
                continue
            media = side_path.parent / side.get("file", "")
            if not side.get("file") or not media.is_file():
                report["failed"].append(key)
                print(f"[ingest {name}] {key}: sidecar names {side.get('file')!r} but the file is missing")
                continue
            seconds = ffmpeg.duration(media)  # raises if the file is not a readable media file
            dest = artifact_path(ctx.paths, job)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(media, dest)
            meta = {"duration_s": round(seconds, 3), "gpu": side.get("gpu"), "gpu_seconds": side.get("seconds"),
                    "settings": side.get("settings"), "versions": side.get("versions"),
                    "finished_at": side.get("finished_at")}
            ctx.manifest.record(job, dest, meta=meta)
            log_event(ctx.paths.runs_log, status="ok", output=ctx.paths.rel(dest), **common)
            report["ingested"].append(key)
            print(f"[ingest {name}] {key}: ok, {seconds:.2f}s, GPU {side.get('seconds')} s on {side.get('gpu')} "
                  f"-> {ctx.paths.rel(dest)}")
    finally:
        if tmp is not None:
            tmp.cleanup()
    summary = ", ".join(f"{k} {len(v)}" for k, v in report.items() if v)
    print(f"[ingest {name}] {summary}")
    return report


def _ms(seconds: Any) -> int | None:
    return int(float(seconds) * 1000) if isinstance(seconds, (int, float)) else None


def _minutes(seconds: Any) -> float | None:
    return round(float(seconds) / 60, 2) if isinstance(seconds, (int, float)) else None
