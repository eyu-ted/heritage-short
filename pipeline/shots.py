"""Stage 3 - shots: give each keyframe motion.

Two backends, chosen per shot in the storyboard:
  wan       image-to-video clip made on Kaggle (Wan 2.2 TI2V-5B), ingested in Phase 6
  kenburns  slow pan/zoom over the still, rendered locally with FFmpeg (deterministic)

The floor that cannot fail: a `wan` shot whose clip has not been made yet falls back to
Ken Burns (if its `fallback` allows), recorded with status "fallback". The fallback is
refreshed when its own inputs change (e.g. a new narration length), and replaced as
soon as the real clip is ingested.

The cache key includes the HASH OF THE KEYFRAME FILE, so a new keyframe invalidates
its shot, and only its shot.

Wan is two steps with two hashes:
  clip    the raw Wan clip (stage "clips", made on Kaggle, see pipeline/kaggle.py). Its hash
          covers what the GPU sees: keyframe file, prompt, seed, size, frames, steps. It does
          NOT include the shot's length, so re-timing the narration never costs GPU time.
  shot    the master made locally from that clip: retimed to the shot's slot (Wan makes
          121 frames = 5 s; slots are 6-10 s) and scaled to the master size.

Output: a square master clip per shot (MASTER x MASTER, 24 fps, no audio). The final
edit crops it to 9:16 and 16:9.
"""
from __future__ import annotations

from typing import Any

from . import ffmpeg
from .cache import Manifest, artifact_path
from .context import Context
from .hashing import hash_file, hash_inputs
from .jobs import Job, NotReadyError
from .runlog import Timer, log_event
from .storyboard import shot_duration, shots_in_order

NAME = "shots"
EXT = "mp4"
PHASE = 4
LOCAL = True  # never calls a provider (Wan clips arrive by `ingest`), so it runs under --offline
MASTER = 1440  # square master; 9:16 crop = 810x1440, 16:9 crop = 1440x810

# ---- Wan generation settings (part of the clip hash) ----------------------------------
CLIP_STAGE = "clips"
# Square, with about the pixel count of the model's 480p / 720p sizes, a multiple of 32
# (Wan 2.2's VAE + patching compress 32x in space), so one clip crops to 9:16 and 16:9.
WAN_SIZE = {"480p": 640, "720p": 960}
WAN_FRAMES = 121  # 4k+1 frames; 121 at 24 fps = 5.04 s, the model's native length
WAN_STEPS = 30  # model card uses 50; 30 is the draft setting measured at Gate 2
WAN_GUIDANCE = 5.0
WAN_STYLE = ("A hand-painted illustration gently coming alive: slow, calm, natural motion; "
             "the painting style, colours and composition stay exactly the same.")
WAN_NEGATIVE = ("fast motion, camera shake, zoom, cut, morphing, warping, flicker, distorted objects, "
                "extra cups, hands, fingers, faces, people appearing, text, watermark, blurry, low quality, "
                "photorealistic, static frozen image")
MAX_SLOWDOWN = 2.0  # stretch a clip at most 2x; any rest of the slot holds the last frame


def wan_prompt(shot: dict[str, Any]) -> str:
    return f"{shot['motion']['prompt'].rstrip('.')}. {WAN_STYLE}"


def clip_inputs(sb: dict[str, Any], shot: dict[str, Any], keyframe_hash: str | None) -> dict[str, Any]:
    return {
        "model": sb["models"]["video"],
        "keyframe": keyframe_hash,
        "prompt": wan_prompt(shot),
        "negative_prompt": WAN_NEGATIVE,
        "seed": shot["motion"]["seed"],
        "size": WAN_SIZE[sb["render"]["video_resolution"]],
        "frames": WAN_FRAMES,
        "steps": WAN_STEPS,
        "guidance": WAN_GUIDANCE,
        "fps": sb["render"]["fps"],
    }


def clip_jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    """The raw Wan clips to make on Kaggle (one per wan shot)."""
    out = []
    for shot in shots_in_order(sb):
        if shot["motion"]["backend"] != "wan":
            continue
        keyframe = manifest.artifact("keyframes", shot["id"])
        keyframe_hash = hash_file(keyframe) if keyframe else None
        blocked = None if keyframe_hash else "needs its keyframe first"
        out.append(Job(CLIP_STAGE, shot["id"], "mp4", clip_inputs(sb, shot, keyframe_hash), blocked))
    return out


def ingested_clip(manifest: Manifest, shot_id: str, clip_hash: str):
    """The raw Wan clip for exactly these inputs, if it has been ingested."""
    entry = manifest.entry(CLIP_STAGE, shot_id)
    if entry and entry.get("hash") == clip_hash:
        return manifest.artifact(CLIP_STAGE, shot_id)
    return None


def narration_seconds(manifest: Manifest, shot_id: str) -> float | None:
    entry = manifest.entry("narration", shot_id)
    if entry and manifest.artifact("narration", shot_id):
        return entry.get("meta", {}).get("duration_s")
    return None


def _kenburns_inputs(sb: dict[str, Any], shot: dict[str, Any], keyframe_hash: str | None,
                     seconds: float | None) -> dict[str, Any]:
    return {
        "backend": "kenburns",
        "keyframe": keyframe_hash,
        "zoom": shot["motion"]["kenburns"]["zoom"],
        "pan": shot["motion"]["kenburns"]["pan"],
        "duration_s": shot_duration(sb, shot, seconds),
        "fps": sb["render"]["fps"],
        "size": MASTER,
    }


def jobs(sb: dict[str, Any], manifest: Manifest) -> list[Job]:
    out = []
    for shot in shots_in_order(sb):
        motion = shot["motion"]
        keyframe = manifest.artifact("keyframes", shot["id"])
        keyframe_hash = hash_file(keyframe) if keyframe else None
        seconds = narration_seconds(manifest, shot["id"])
        blocked = None if keyframe_hash else "needs its keyframe first"
        if blocked is None and seconds is None:
            blocked = "needs narration timing first"

        if motion["backend"] == "wan":
            clip = Job(CLIP_STAGE, shot["id"], "mp4", clip_inputs(sb, shot, keyframe_hash))
            inputs = {
                "backend": "wan",
                "clip": clip.hash,
                "keyframe": keyframe_hash,
                "duration_s": shot_duration(sb, shot, seconds),
                "fps": sb["render"]["fps"],
                "size": MASTER,
                "max_slowdown": MAX_SLOWDOWN,
            }
        else:
            inputs = _kenburns_inputs(sb, shot, keyframe_hash, seconds)
        out.append(Job(NAME, shot["id"], EXT, inputs, blocked))
    return out


def _fallback_hash(ctx: Context, job: Job) -> str:
    shot = next(s for s in ctx.sb["shots"] if s["id"] == job.key)
    seconds = narration_seconds(ctx.manifest, job.key)
    return hash_inputs(_kenburns_inputs(ctx.sb, shot, job.inputs["keyframe"], seconds))


def is_fresh(ctx: Context, job: Job) -> bool:
    """A fallback is fresh only while its own Ken Burns inputs are unchanged AND the real
    Wan clip has still not arrived (once it is ingested, the shot is rebuilt from it)."""
    if not ctx.manifest.is_fresh(job):
        return False
    entry = ctx.manifest.entry(NAME, job.key)
    if entry.get("status") == "fallback":
        if ingested_clip(ctx.manifest, job.key, job.inputs["clip"]):
            return False
        return entry.get("meta", {}).get("fallback_hash") == _fallback_hash(ctx, job)
    return True


def retime_filter(clip_s: float, target_s: float, fps: int, size: int) -> str:
    """Stretch a short Wan clip toward its slot (frame blending keeps slow motion smooth),
    hold the last frame for any rest, then scale to the square master."""
    factor = min(MAX_SLOWDOWN, max(1.0, target_s / clip_s))
    parts = ["crop='min(iw,ih)':'min(iw,ih)'"]
    if factor > 1.001:
        parts.append(f"setpts={factor:.5f}*PTS,minterpolate=fps={fps}:mi_mode=blend")
    else:
        parts.append(f"fps={fps}")
    parts += [f"tpad=stop_mode=clone:stop_duration={target_s:.3f}",
              f"scale={size}:{size}:flags=lanczos", "format=yuv420p"]
    return ",".join(parts)


def render_from_clip(clip_path, out_path, inputs: dict[str, Any]) -> float:
    clip_s = ffmpeg.duration(clip_path)
    fps, target = inputs["fps"], inputs["duration_s"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(clip_path), "-vf", retime_filter(clip_s, target, fps, inputs["size"]),
                "-frames:v", str(max(1, round(target * fps))), "-c:v", "libx264", "-preset", "medium",
                "-crf", "18", "-r", str(fps), "-an", str(out_path)])
    return clip_s


def zoompan_filter(zoom: float, pan: str, frames: int, size: int, fps: int) -> str:
    """Slow push-in with an optional drift. Source is upscaled 2x first to avoid zoompan jitter."""
    n = max(1, frames - 1)
    z = f"1+({zoom}-1)*on/{n}"
    free_x, free_y = "(iw-iw/zoom)", "(ih-ih/zoom)"
    x = {"left": f"{free_x}*(1-on/{n})", "right": f"{free_x}*on/{n}"}.get(pan, f"{free_x}/2")
    y = {"up": f"{free_y}*(1-on/{n})", "down": f"{free_y}*on/{n}"}.get(pan, f"{free_y}/2")
    big = 2 * size
    return (f"scale={big}:{big}:force_original_aspect_ratio=increase:flags=lanczos,crop={big}:{big},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={size}x{size}:fps={fps},format=yuv420p")


def render_kenburns(keyframe_path, out_path, inputs: dict[str, Any]) -> None:
    fps = inputs["fps"]
    frames = max(1, round(inputs["duration_s"] * fps))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-loop", "1", "-framerate", str(fps), "-i", str(keyframe_path),
                "-vf", zoompan_filter(inputs["zoom"], inputs["pan"], frames, inputs["size"], fps),
                "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-r", str(fps), "-an", str(out_path)])


def run(ctx: Context, todo: list[Job]) -> None:
    shots = {s["id"]: s for s in ctx.sb["shots"]}
    for job in todo:
        shot = shots[job.key]
        keyframe = ctx.manifest.artifact("keyframes", job.key)
        seconds = narration_seconds(ctx.manifest, job.key)
        kb_inputs = _kenburns_inputs(ctx.sb, shot, job.inputs["keyframe"], seconds)

        if job.inputs["backend"] == "wan":
            clip = ingested_clip(ctx.manifest, job.key, job.inputs["clip"])
            if clip:
                path = artifact_path(ctx.paths, job)
                timer = Timer()
                with timer:
                    clip_s = render_from_clip(clip, path, job.inputs)
                factor = min(MAX_SLOWDOWN, max(1.0, job.inputs["duration_s"] / clip_s))
                ctx.manifest.record(job, path, meta={"duration_s": job.inputs["duration_s"], "render": "wan",
                                                     "clip": ctx.paths.rel(clip), "slowdown": round(factor, 3),
                                                     "render_ms": timer.ms})
                log_event(ctx.paths.runs_log, stage=NAME, shot_id=job.key, provider="local",
                          model="ffmpeg-retime", params={"clip_s": round(clip_s, 3), "slowdown": round(factor, 3),
                                                         "duration_s": job.inputs["duration_s"]},
                          input_hash=job.hash, output=ctx.paths.rel(path), latency_ms=timer.ms, status="ok")
                print(f"[shots] {job.key}: Wan clip {clip_s:.2f}s retimed x{factor:.2f} to "
                      f"{job.inputs['duration_s']:.2f}s -> {ctx.paths.rel(path)}")
                continue
            if shot["motion"]["fallback"] != "kenburns":
                raise NotReadyError(f"shots: {job.key} needs its Wan clip (Phase 6) and has no fallback")
            path = artifact_path(ctx.paths, job)  # same hash as the Wan master will have, so mark the file
            path = path.with_name(f"{path.stem}-kenburns{path.suffix}")
            status, meta = "fallback", {"fallback_hash": hash_inputs(kb_inputs), "reason": "wan clip not ingested yet"}
        else:
            path = artifact_path(ctx.paths, job)
            status, meta = "ok", {}

        timer = Timer()
        with timer:
            render_kenburns(keyframe, path, kb_inputs)
        meta.update({"duration_s": kb_inputs["duration_s"], "render": "kenburns", "render_ms": timer.ms})
        ctx.manifest.record(job, path, status=status, meta=meta)
        log_event(ctx.paths.runs_log, stage=NAME, shot_id=job.key, provider="local", model="ffmpeg-zoompan",
                  params={k: kb_inputs[k] for k in ("zoom", "pan", "duration_s", "size")},
                  input_hash=job.hash, output=ctx.paths.rel(path), latency_ms=timer.ms,
                  status="fallback" if status == "fallback" else "ok",
                  note="Ken Burns stands in until the Wan clip is ingested" if status == "fallback" else None)
        label = " (fallback for wan)" if status == "fallback" else ""
        print(f"[shots] {job.key}{label}: {kb_inputs['duration_s']:.2f}s Ken Burns in {timer.ms} ms -> {ctx.paths.rel(path)}")
