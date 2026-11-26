"""The radio cut and the animatic: cheap prototypes that share the final edit's timeline.

  radio     narration over placeholder music on a black screen, English subtitles (16:9).
            The audio animatic: tests the story and its timing before any picture exists.
  animatic  the same soundtrack and subtitles, with each shot's clip as picture,
            cropped to vertical 9:16 (the phone format the audience watches in).

Both use the same timeline, subtitle and ducking settings as the final edit, so what
testers see and hear is what the film will do.
Outputs: outputs/final/radio_cut.mp4 (+ .srt), outputs/final/animatic_9x16.mp4 (+ .srt)
"""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg, subtitles, timeline
from .context import Context
from .jobs import NotReadyError
from .storyboard import shots_in_order

# A soft A/E drone as placeholder music: deliberately plain, it only stands in for the score.
PAD_EXPR = "0.10*sin(2*PI*110*t)+0.07*sin(2*PI*164.81*t)+0.05*sin(2*PI*220*t)"
FORMATS = {
    False: {"name": "radio_cut", "size": (1280, 720)},
    True: {"name": "animatic_9x16", "size": (720, 1280)},
}


def _need(ctx: Context, stage: str) -> dict[str, Path]:
    found, missing = {}, []
    for shot in shots_in_order(ctx.sb):
        path = ctx.manifest.artifact(stage, shot["id"])
        (found.__setitem__(shot["id"], path) if path else missing.append(shot["id"]))
    if missing:
        raise NotReadyError(f"{stage} missing for {missing}; run `python -m pipeline {stage}` first")
    return found


MUSIC_BED_LUFS = -26  # the score sits well under the voice before ducking


def audio_graph(slots: list[timeline.Slot], total: float, first: int, duck: dict, loudness: dict,
                music: bool = False, master: bool = True, voice: str = "") -> list[str]:
    """Narration inputs are [first .. first+n-1]; input first+n is the music: the placeholder
    pad, or (music=True) a real score candidate, levelled, trimmed to the film and faded out.
    master=False leaves out the final one-pass loudnorm (the final edit measures and masters
    the mix itself, see assemble.py); `voice` is an optional filter chain for the narration bus."""
    n = len(slots)
    parts = []
    for i, slot in enumerate(slots):
        parts.append(f"[{first + i}:a]aresample=48000,adelay={int(round(slot.narration_start * 1000))}:all=1[n{i}]")
    parts.append("".join(f"[n{i}]" for i in range(n)) +
                 f"amix=inputs={n}:normalize=0:duration=longest,apad=whole_dur={total}[narr]")
    parts.append(f"[narr]{voice + ',' if voice else ''}asplit=2[narr_main][narr_sc]")
    fade = f"afade=t=out:st={max(0.0, total - 3)}:d=3"
    if music:
        parts.append(f"[{first + n}:a]aresample=48000,atrim=0:{total},asetpts=PTS-STARTPTS,"
                     f"loudnorm=I={MUSIC_BED_LUFS}:TP=-3:LRA=11,aresample=48000,afade=t=in:d=1.5,{fade},"
                     f"apad=whole_dur={total}[pad]")
    else:
        parts.append(f"[{first + n}:a]aresample=48000,lowpass=f=900,tremolo=f=0.15:d=0.3,"
                     f"afade=t=in:d=2,{fade},volume=-10dB[pad]")
    parts.append(f"[pad][narr_sc]sidechaincompress=threshold={duck['threshold']}:ratio={duck['ratio']}:"
                 f"attack={duck['attack_ms']}:release={duck['release_ms']}[ducked]")
    final = f"loudnorm=I={loudness['I']}:TP={loudness['TP']}:LRA=11," if master else ""
    parts.append(f"[narr_main][ducked]amix=inputs=2:normalize=0:duration=first,{final}aresample=48000[aout]")
    return parts


def picture_graph(slots: list[timeline.Slot], size: tuple[int, int], fps: int, endcard_s: float) -> list[str]:
    """Shot clips are inputs [0 .. n-1]: crop each to the frame's aspect, hold the last frame
    if a clip is shorter than its slot (Wan clips are ~5 s), then join and add the end-card time."""
    w, h = size
    parts = []
    for i, slot in enumerate(slots):
        parts.append(f"[{i}:v]crop='min(iw,ih*{w}/{h})':'min(ih,iw*{h}/{w})',scale={w}:{h}:flags=lanczos,"
                     f"setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={slot.duration},"
                     f"trim=duration={slot.duration},setpts=PTS-STARTPTS[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(len(slots))) +
                 f"concat=n={len(slots)}:v=1:a=0,tpad=stop_mode=add:stop_duration={endcard_s}:color=black[pic]")
    return parts


def build(ctx: Context, picture: bool = False, music_key: str | None = None) -> Path:
    """music_key: audition a score candidate (output gets its name); otherwise the chosen
    score if there is one, else the placeholder pad."""
    from . import music

    fmt = FORMATS[picture]
    narr_paths = _need(ctx, "narration")
    seconds = {sid: float(ctx.manifest.entry("narration", sid)["meta"]["duration_s"]) for sid in narr_paths}
    slots, total = timeline.build(ctx.sb, seconds)

    key = music_key or ctx.sb["music"]["chosen"]
    music_path = music.candidate_path(ctx, key) if key else None
    if key and music_path is None:
        raise NotReadyError(f"music {key!r} is not ingested for the current inputs "
                            "(`python -m pipeline ingest music --from <download>`)")
    name = f"{fmt['name']}__{music_key}" if music_key else fmt["name"]

    out_dir = ctx.paths.outputs / "final"
    out_dir.mkdir(parents=True, exist_ok=True)
    fps, (w, h) = ctx.sb["render"]["fps"], fmt["size"]
    srt_name, ass_name, mp4_name = f"{fmt['name']}.srt", f"{fmt['name']}.ass", f"{name}.mp4"
    cues = subtitles.cues_for(slots)
    (out_dir / srt_name).write_text(subtitles.to_srt(cues), encoding="utf-8")  # the deliverable file
    (out_dir / ass_name).write_text(subtitles.to_ass(cues, w, h), encoding="utf-8")  # pixel-exact burn-in
    args: list[str] = []
    if picture:
        shot_paths = _need(ctx, "shots")
        for slot in slots:
            args += ["-i", str(shot_paths[slot.shot_id].resolve())]
        graph = picture_graph(slots, (w, h), fps, float(ctx.sb["endcard"]["duration_s"]))
        video_label, first_audio = "[pic]", len(slots)
    else:
        args += ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}:d={total}"]
        graph, video_label, first_audio = [], "[0:v]", 1
    for slot in slots:
        args += ["-i", str(narr_paths[slot.shot_id].resolve())]
    if music_path:
        args += ["-i", str(music_path.resolve())]
    else:
        args += ["-f", "lavfi", "-i", f"aevalsrc=exprs={PAD_EXPR}:s=48000:d={total}"]

    graph += audio_graph(slots, total, first_audio, ctx.sb["mix"]["duck"], ctx.sb["mix"]["loudness"],
                         music=music_path is not None)
    graph.append(f"{video_label}subtitles={ass_name}[vout]")
    args += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]", "-t", str(total),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(fps),
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", mp4_name]
    # Run inside the output folder so the subtitles filter gets a plain relative path
    # (Windows drive letters need awkward escaping inside FFmpeg filter graphs).
    ffmpeg.run(args, cwd=out_dir)

    out = out_dir / mp4_name
    print(f"[{fmt['name']}] {ctx.paths.rel(out)}  ({total:.1f}s, {w}x{h}, subtitles: {srt_name}, "
          f"music: {key or 'placeholder pad'})")
    for slot in slots:
        print(f"  {slot.shot_id}  {slot.start:6.2f}s  +{slot.duration:5.2f}s  narration {slot.narration_s:.2f}s")
    return out
