"""Stage 5 - assemble: the final edit, done entirely with FFmpeg (deterministic, no AI).

One job per output format (9:16 vertical, 16:9 horizontal). Both share one audio master:

  audio    narration (lightly compressed) placed on the shared timeline + the chosen score
           (or the placeholder bed while no score is chosen), ducked under the voice. Then
           measured mastering: pass 1 measures the mix, pass 2 applies one gain to the
           loudness target plus a peak limiter, and the result is measured again (and the
           gain corrected if it missed by more than 0.2 LU).
  picture  each shot master centre-cropped to the format, 0.5 s crossfades that keep every
           shot's start on the narration timeline, a 1 s fade to black, then the end card
           ("Made with AI" + title), drawn by the same renderer as the burned-in subtitles.
  checks   the delivered MP4 is measured again (duration, size, fps, loudness, true peak);
           the numbers go into the manifest and runs.jsonl, and misses are printed.

The cache key holds the hash of every input file plus the mix, subtitle, end-card and encode
settings, so a film is re-rendered only when something it is made of changed.
Outputs: outputs/assemble/film_9x16__<hash>.mp4, film_16x9__<hash>.mp4, outputs/final/buna_en.srt
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from . import ffmpeg, music, radio, subtitles, timeline
from .cache import Manifest, artifact_path
from .context import Context
from .hashing import hash_file
from .jobs import Job, NotReadyError
from .runlog import Timer, log_event
from .storyboard import shots_in_order

NAME = "assemble"
EXT = "mp4"
PHASE = 7
LOCAL = True  # FFmpeg only: runs under --offline
RECIPE = 2  # 2: oversampled limiter. Bump when the edit recipe below changes, so cached films are rebuilt

FORMATS = {"9x16": (1080, 1920), "16x9": (1920, 1080)}
FADE_TO_BLACK_S = 1.0
# AAC encoding can raise true peaks by a few tenths of a dB, so the master aims this much
# below the storyboard's true-peak limit and the delivered file still meets it.
AAC_HEADROOM_DB = 0.5
# The limiter runs 4x oversampled (it only sees samples; at 48 kHz the first master's true
# peaks overshot its limit by 1.2 dB). This margin covers what is left of that overshoot.
LIMITER_MARGIN_DB = 0.5
LOUDNESS_TOLERANCE = 0.2  # LU
# Narration bus: gentle 2.5:1 above -18 dBFS, so the limiter does not have to do all the work.
VOICE_COMPRESSOR = "acompressor=threshold=0.125:ratio=2.5:attack=8:release=150:knee=4"
ENCODE = {"vcodec": "libx264", "preset": "medium", "crf": 20, "acodec": "aac", "audio_bitrate": "192k"}
SRT_NAME = "buna_en.srt"


def music_source(sb: dict[str, Any], manifest: Manifest) -> tuple[str | None, Path | None, str | None]:
    """(chosen key, its WAV, problem). No choice yet -> (None, None, None): the placeholder bed."""
    chosen = sb["music"]["chosen"]
    if not chosen:
        return None, None, None
    job = next((j for j in music.jobs(sb, manifest) if j.key == chosen), None)
    if job is None:
        return chosen, None, f"music.chosen {chosen!r} is not one of the candidates"
    if not manifest.is_fresh(job):
        return chosen, None, (f"chosen music {chosen!r} is not ingested for the current cue settings "
                              "(ingest it, or set music.chosen to null to use the placeholder bed)")
    return chosen, manifest.artifact("music", chosen), None


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
    key, music_path, problem = music_source(sb, manifest)
    common = {
        "recipe": RECIPE,
        "parts": parts,
        "music": hash_file(music_path) if music_path else (None if key else f"placeholder:{radio.PAD_EXPR}"),
        "subtitles": [s["narration"]["en"] for s in shots_in_order(sb)],
        "mix": sb["mix"],
        "endcard": sb["endcard"],
        "reframe": sb["project"]["reframe"],
        "fps": sb["render"]["fps"],
        "crossfade_s": sb["render"]["crossfade_s"],
        "fade_to_black_s": FADE_TO_BLACK_S,
        "mastering": {"voice": VOICE_COMPRESSOR, "aac_headroom_db": AAC_HEADROOM_DB,
                      "limiter_margin_db": LIMITER_MARGIN_DB, "tolerance": LOUDNESS_TOLERANCE},
        "encode": ENCODE,
    }
    blocked = problem
    if missing:
        blocked = f"waiting for {len(missing)} inputs (e.g. {', '.join(missing[:3])})"
    return [Job(NAME, f"film_{fmt}", EXT, {**common, "format": fmt, "size": list(FORMATS[fmt])}, blocked)
            for fmt in sb["project"]["outputs"]]


# ---- audio ------------------------------------------------------------------------------

def audio_master(ctx: Context, slots: list[timeline.Slot], total: float, narr: dict[str, Path],
                 music_path: Path | None, tmp: Path) -> tuple[Path, dict[str, Any]]:
    """Mix once (voice lightly compressed), measure it, then master: one gain to the loudness
    target + a peak limiter, measured again and corrected if it missed by more than
    LOUDNESS_TOLERANCE. Returns the master WAV and the measurements.

    (The TTS voice has ~19 dB between its peaks and its loudness; -14 LUFS with peaks under
    -1.5 dBTP allows ~12.5 dB. loudnorm's linear mode cannot do that, and its dynamic
    fallback landed at -15.0 LUFS in the first assembly, so the peaks are handled explicitly.)"""
    target = ctx.sb["mix"]["loudness"]
    i_target = float(target["I"])
    limit_db = float(target["TP"]) - AAC_HEADROOM_DB - LIMITER_MARGIN_DB
    args: list[str] = []
    for slot in slots:
        args += ["-i", str(narr[slot.shot_id].resolve())]
    if music_path:
        args += ["-i", str(music_path.resolve())]
    else:
        args += ["-f", "lavfi", "-i", f"aevalsrc=exprs={radio.PAD_EXPR}:s=48000:d={total}"]
    graph = radio.audio_graph(slots, total, 0, ctx.sb["mix"]["duck"], target, music=music_path is not None,
                              master=False, voice=VOICE_COMPRESSOR)
    premix = tmp / "premix.wav"
    ffmpeg.run(args + ["-filter_complex", ";".join(graph), "-map", "[aout]", "-t", str(total),
                       "-c:a", "pcm_f32le", str(premix)])

    first = ffmpeg.loudness(premix, i_target, float(target["TP"]))
    gain = i_target - first["input_i"]
    master = tmp / "master.wav"
    for attempt in range(1, 4):
        ffmpeg.run(["-i", str(premix), "-af",
                    # 4x oversampled, so the limiter sees the peaks between samples too
                    f"volume={gain:.3f}dB,aresample=192000,"
                    f"alimiter=limit={10 ** (limit_db / 20):.4f}:attack=5:release=60:level=0,aresample=48000",
                    "-c:a", "pcm_s24le", str(master)])
        result = ffmpeg.loudness(master, i_target, float(target["TP"]))
        miss = i_target - result["input_i"]
        if abs(miss) <= LOUDNESS_TOLERANCE:
            break
        gain += miss  # the limiter took some loudness away; push the gain by what is missing
    return master, {"premix_lufs": round(first["input_i"], 2), "premix_tp": round(first["input_tp"], 2),
                    "gain_db": round(gain, 2), "limit_dbfs": limit_db, "attempts": attempt,
                    "master_lufs": round(result["input_i"], 2), "master_tp": round(result["input_tp"], 2)}


# ---- picture ----------------------------------------------------------------------------

def picture_graph(slots: list[timeline.Slot], size: tuple[int, int], fps: int, crossfade_s: float,
                  fade_s: float) -> list[str]:
    """Shot masters are inputs [0 .. n-1], the black end-card background is input n.

    Each shot is lengthened by the transition after it, and transition i starts exactly at
    shot i+1's slot start, so the crossfades never shift the picture against the narration:
    after xfade i the stream is (slot[i+1].start + length of shot i+1) long."""
    w, h = size
    n = len(slots)
    parts = []
    for i, slot in enumerate(slots):
        length = slot.duration + (crossfade_s if i < n - 1 else fade_s)
        parts.append(f"[{i}:v]crop='min(iw,ih*{w}/{h})':'min(ih,iw*{h}/{w})',scale={w}:{h}:flags=lanczos,"
                     f"setsar=1,fps={fps},format=yuv420p,tpad=stop_mode=clone:stop_duration={length:.3f},"
                     f"trim=duration={length:.3f},setpts=PTS-STARTPTS[v{i}]")
    parts.append(f"[{n}:v]fps={fps},format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v{n}]")
    prev = "v0"
    for i in range(n):
        last = i == n - 1
        offset = slots[i].end if last else slots[i + 1].start
        kind, dur = ("fadeblack", fade_s) if last else ("fade", crossfade_s)
        out = "pic" if last else f"x{i}"
        parts.append(f"[{prev}][v{i + 1}]xfade=transition={kind}:duration={dur}:offset={offset:.3f}[{out}]")
        prev = out
    return parts


def render(ctx: Context, job: Job, slots: list[timeline.Slot], total: float, shot_paths: dict[str, Path],
           master: Path, tmp: Path, out: Path) -> None:
    w, h = job.inputs["size"]
    fps = job.inputs["fps"]
    card_s = float(ctx.sb["endcard"]["duration_s"])
    card = subtitles.Card(round(total - card_s + 0.2, 3), total, ctx.sb["endcard"]["text"],
                          ctx.sb["endcard"].get("subtitle", ""))
    ass = f"{job.key}.ass"
    (tmp / ass).write_text(subtitles.to_ass(subtitles.cues_for(slots), w, h, card), encoding="utf-8")

    args: list[str] = []
    for slot in slots:
        args += ["-i", str(shot_paths[slot.shot_id].resolve())]
    args += ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}:d={card_s}"]
    args += ["-i", str(master)]
    graph = picture_graph(slots, (w, h), fps, job.inputs["crossfade_s"], job.inputs["fade_to_black_s"])
    graph.append(f"[pic]subtitles={ass}[vout]")
    enc = job.inputs["encode"]
    out.parent.mkdir(parents=True, exist_ok=True)
    args += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", f"{len(slots) + 1}:a",
             "-t", str(total), "-c:v", enc["vcodec"], "-preset", enc["preset"], "-crf", str(enc["crf"]),
             "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", enc["acodec"], "-b:a", enc["audio_bitrate"],
             "-ar", "48000", "-movflags", "+faststart", str(out.resolve())]
    # Run inside the temp folder so the subtitles filter gets a plain relative path
    # (Windows drive letters need awkward escaping inside FFmpeg filter graphs).
    ffmpeg.run(args, cwd=tmp)


def check(ctx: Context, path: Path, size: list[int]) -> dict[str, Any]:
    """Measure the delivered file and compare with the brief's targets."""
    info = ffmpeg.probe(path)
    loud = ffmpeg.loudness(path)
    target = ctx.sb["mix"]["loudness"]
    span = ctx.sb["project"]["target_duration_s"]
    video = info.get("video", {})
    result = {
        "duration_s": info["duration_s"],
        "size": [video.get("width"), video.get("height")],
        "fps": video.get("fps"),
        "lufs": round(loud["input_i"], 2),
        "true_peak_dbtp": round(loud["input_tp"], 2),
        "lra": round(loud["input_lra"], 2),
    }
    result["problems"] = [p for p in (
        None if span["min"] <= info["duration_s"] <= span["max"] else
        f"duration {info['duration_s']}s outside {span['min']}-{span['max']}s",
        None if result["size"] == list(size) else f"size {result['size']} != {size}",
        None if video.get("fps") == ctx.sb["render"]["fps"] else f"fps {video.get('fps')}",
        None if abs(loud["input_i"] - target["I"]) <= 1.0 else f"loudness {result['lufs']} LUFS (target {target['I']})",
        None if loud["input_tp"] <= target["TP"] else f"true peak {result['true_peak_dbtp']} dBTP > {target['TP']}",
    ) if p]
    return result


def run(ctx: Context, todo: list[Job]) -> None:
    if not todo:
        return
    narr = radio._need(ctx, "narration")
    shot_paths = radio._need(ctx, "shots")
    seconds = {sid: float(ctx.manifest.entry("narration", sid)["meta"]["duration_s"]) for sid in narr}
    slots, total = timeline.build(ctx.sb, seconds)
    key, music_path, problem = music_source(ctx.sb, ctx.manifest)
    if problem:
        raise NotReadyError(problem)
    music_label = key or "placeholder bed"
    if key is None:
        print("[assemble] note: no score chosen yet (storyboard music.chosen); using the placeholder bed")

    final_dir = ctx.paths.outputs / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    (final_dir / SRT_NAME).write_text(subtitles.to_srt(subtitles.cues_for(slots)), encoding="utf-8")
    shot_render = {s.shot_id: (ctx.manifest.entry("shots", s.shot_id) or {}).get("meta", {}).get("render", "kenburns")
                   for s in slots}

    with tempfile.TemporaryDirectory(prefix="buna-assemble-") as tmp_name:
        tmp = Path(tmp_name)
        with Timer() as audio_timer:
            master, mastering = audio_master(ctx, slots, total, narr, music_path, tmp)
        print(f"[assemble] audio master: mix {mastering['premix_lufs']:.1f} LUFS / {mastering['premix_tp']:.1f} dBTP"
              f" -> gain {mastering['gain_db']:+.1f} dB, limiter {mastering['limit_dbfs']:.1f} dBFS -> "
              f"{mastering['master_lufs']:.1f} LUFS / {mastering['master_tp']:.1f} dBTP "
              f"({mastering['attempts']} pass(es), {audio_timer.ms} ms); music: {music_label}")
        for job in todo:
            out = artifact_path(ctx.paths, job)
            with Timer() as timer:
                render(ctx, job, slots, total, shot_paths, master, tmp, out)
            result = check(ctx, out, job.inputs["size"])
            meta = {**result, "music": key or "placeholder", "shots": shot_render,
                    "mastering": mastering, "render_ms": timer.ms, "audio_ms": audio_timer.ms}
            ctx.manifest.record(job, out, meta=meta)
            log_event(ctx.paths.runs_log, stage=NAME, shot_id=job.key, provider="local", model="ffmpeg",
                      params={"size": job.inputs["size"], "music": key or "placeholder",
                              "wan_shots": sorted(k for k, v in shot_render.items() if v == "wan"),
                              "lufs": result["lufs"], "true_peak_dbtp": result["true_peak_dbtp"]},
                      input_hash=job.hash, output=ctx.paths.rel(out), latency_ms=timer.ms + audio_timer.ms,
                      status="ok", note="; ".join(result["problems"]) or None)
            w, h = job.inputs["size"]
            print(f"[assemble] {job.key}: {result['duration_s']:.1f}s {w}x{h} {result['fps']:g} fps, "
                  f"{result['lufs']:.1f} LUFS, {result['true_peak_dbtp']:.1f} dBTP, in {timer.ms / 1000:.0f} s "
                  f"-> {ctx.paths.rel(out)}")
            for problem in result["problems"]:
                print(f"[assemble]   CHECK: {problem}")
    print(f"[assemble] subtitles: {ctx.paths.rel(final_dir / SRT_NAME)}")
