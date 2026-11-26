"""Stage 1 - narration: one Amharic WAV per shot from Gemini TTS.

Cache key per line: model, language, text, voice, style. Change one line -> one new WAV.

Quota strategy (FAILURES F7, F8): the free tier allows 10 TTS requests per model
per day. So:
  - a line that is already cached is never requested again;
  - with `narration_defaults.batch`, all pending lines go out in ONE request,
    separated by long pauses, and the audio is cut at its longest silences
    (pipeline/audio_split.py). If the cut is not plausible, it falls back to one
    request per line;
  - a quota error stops the stage cleanly: finished lines stay cached and the
    next run continues where this one stopped.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from . import audio_split
from .cache import Manifest, artifact_path
from .calls import logged_call
from .config import require_env
from .context import Context
from .hashing import hash_file, hash_inputs
from .jobs import Job
from .providers.gemini import AudioResult, Gemini, pcm_to_wav, split_c2pa
from .runlog import log_event
from .storyboard import shots_in_order

NAME = "narration"
EXT = "wav"
PHASE = 3
BATCH_PAUSE_HINT = "Leave a long, clear pause of about two seconds between paragraphs."


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


def _cost(r: AudioResult) -> dict[str, Any]:
    return {"unit": "tokens", "input": r.input_tokens, "output": r.output_tokens, "audio_s": round(r.duration_s, 2)}


def _keep_provenance(ctx: Context, wav_path: Path, manifest_bytes: bytes | None) -> dict[str, Any]:
    """Store the provider's C2PA content credential next to the WAV (it cannot live inside
    our re-encoded audio) and say where it is."""
    if not manifest_bytes:
        return {}
    c2pa_path = wav_path.with_suffix(".c2pa")
    c2pa_path.write_bytes(manifest_bytes)
    return {"c2pa": ctx.paths.rel(c2pa_path), "c2pa_bytes": len(manifest_bytes)}


def _save(ctx: Context, job: Job, pcm: bytes, rate: int, meta: dict[str, Any],
          provenance: bytes | None = None) -> None:
    path = artifact_path(ctx.paths, job)
    pcm_to_wav(pcm, rate, path)
    duration = len(pcm) / 2 / rate
    ctx.manifest.record(job, path, meta={"duration_s": round(duration, 3), "sample_rate": rate,
                                         "voice": job.inputs["voice"], **meta,
                                         **_keep_provenance(ctx, path, provenance)})
    print(f"[narration] {job.key}: {duration:.2f}s -> {ctx.paths.rel(path)}")


def repair_c2pa(ctx: Context) -> list[str]:
    """One-time repair for lines recorded before the provider split the C2PA credential off
    (FAILURES F11): cut the credential out of the WAV's samples, keep it as a .c2pa sidecar,
    correct the recorded duration. Idempotent; no TTS request is made."""
    repaired = []
    for key, entry in sorted(ctx.manifest.data["stages"].get(NAME, {}).items()):
        path = ctx.paths.abs(entry["path"])
        if not path.exists():
            continue
        with wave.open(str(path)) as wav:
            rate, raw = wav.getframerate(), wav.readframes(wav.getnframes())
        pcm, credential = split_c2pa(raw)
        if credential is None:
            continue
        before = hash_file(path)
        pcm_to_wav(pcm, rate, path)
        meta = {**entry["meta"], "duration_s": round(len(pcm) / 2 / rate, 3),
                **_keep_provenance(ctx, path, credential)}
        entry.update(meta=meta)
        ctx.manifest.save()
        log_event(ctx.paths.runs_log, stage=NAME, shot_id=key, provider="local", model="repair-c2pa",
                  input_hash=entry["hash"], output=entry["path"], status="ok",
                  params={"removed_bytes": len(raw) - len(pcm), "file_before": before, "file_after": hash_file(path),
                          "duration_s": meta["duration_s"]},
                  note="C2PA credential was being played as audio; split off into a .c2pa sidecar (FAILURES F11)")
        print(f"[narration] {key}: removed {len(raw) - len(pcm)} bytes of C2PA data from the audio "
              f"-> {meta['duration_s']:.2f}s; credential kept in {meta['c2pa']}")
        repaired.append(key)
    return repaired


def _run_single(ctx: Context, gem: Gemini, job: Job) -> None:
    i = job.inputs
    audio = logged_call(
        ctx.paths,
        lambda: gem.tts(i["model"], i["text"], voice=i["voice"], style=i["style"]),
        stage=NAME, provider="gemini", model=i["model"], shot_id=job.key,
        params={"voice": i["voice"], "style": i["style"], "language": i["language"], "mode": "single"},
        input_hash=job.hash, output=ctx.paths.rel(artifact_path(ctx.paths, job)), cost=_cost,
    )
    _save(ctx, job, audio.pcm, audio.sample_rate, {"mode": "single"}, audio.provenance)


def _run_batch(ctx: Context, gem: Gemini, group: list[Job]) -> None:
    first = group[0].inputs
    texts = [j.inputs["text"] for j in group]
    style = f"{first['style'].rstrip('.')}. {BATCH_PAUSE_HINT}"
    batch_hash = hash_inputs({"model": first["model"], "voice": first["voice"], "style": style,
                              "language": first["language"], "texts": texts})
    batch_path = ctx.paths.outputs / NAME / f"batch__{batch_hash}.wav"
    keys = ",".join(j.key for j in group)

    audio = logged_call(
        ctx.paths,
        lambda: gem.tts(first["model"], "\n\n".join(texts), voice=first["voice"], style=style),
        stage=NAME, provider="gemini", model=first["model"], shot_id=keys,
        params={"voice": first["voice"], "style": style, "language": first["language"],
                "mode": "batch", "lines": len(group)},
        input_hash=batch_hash, output=ctx.paths.rel(batch_path), cost=_cost,
    )
    pcm_to_wav(audio.pcm, audio.sample_rate, batch_path)  # keep the uncut take as evidence
    _keep_provenance(ctx, batch_path, audio.provenance)  # one credential covers the whole take
    pieces = audio_split.split(audio.pcm, audio.sample_rate, texts)
    for idx, (job, piece) in enumerate(zip(group, pieces)):
        _save(ctx, job, piece, audio.sample_rate, {"mode": "batch", "batch": batch_hash, "segment": idx})


def run(ctx: Context, todo: list[Job]) -> None:
    if not todo:
        return
    gem = Gemini(require_env("GEMINI_API_KEY"))
    if not (ctx.sb["narration_defaults"].get("batch") and len(todo) > 1):
        for job in todo:
            _run_single(ctx, gem, job)
        return

    groups: dict[tuple, list[Job]] = {}
    for job in todo:  # one request per voice setting; normally all lines share one
        i = job.inputs
        groups.setdefault((i["model"], i["voice"], i["style"], i["language"]), []).append(job)
    for group in groups.values():
        if len(group) > 1:
            try:
                _run_batch(ctx, gem, group)
                continue
            except audio_split.SplitError as err:
                print(f"[narration] batch cut rejected ({err}); falling back to one request per line")
                log_event(ctx.paths.runs_log, stage=NAME, provider="gemini", model=group[0].inputs["model"],
                          status="fallback", note=f"batch split rejected: {err}")
        for job in group:
            _run_single(ctx, gem, job)
