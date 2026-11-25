"""The radio cut: narration over placeholder music on a black screen, with English subtitles.

It is the cheapest prototype of the film (an audio animatic): it tests the story
and its timing with real people before any picture is generated. It uses the
same timeline, subtitle and ducking settings the final edit will use.

Output: outputs/final/radio_cut.mp4 and radio_cut.srt
"""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg, subtitles, timeline
from .context import Context
from .jobs import NotReadyError
from .storyboard import shots_in_order

OUT_NAME = "radio_cut"
SIZE = "1280x720"
# A soft A/E drone as placeholder music: deliberately plain, it only stands in for the score.
PAD_EXPR = "0.10*sin(2*PI*110*t)+0.07*sin(2*PI*164.81*t)+0.05*sin(2*PI*220*t)"


def _narration(ctx: Context) -> dict[str, tuple[Path, float]]:
    found, missing = {}, []
    for shot in shots_in_order(ctx.sb):
        path = ctx.manifest.artifact("narration", shot["id"])
        entry = ctx.manifest.entry("narration", shot["id"])
        if path and entry and entry.get("meta", {}).get("duration_s"):
            found[shot["id"]] = (path, float(entry["meta"]["duration_s"]))
        else:
            missing.append(shot["id"])
    if missing:
        raise NotReadyError(f"narration missing for {missing}; run `python -m pipeline narration` first")
    return found


def filter_graph(slots: list[timeline.Slot], total: float, duck: dict, loudness: dict, srt_name: str) -> str:
    n = len(slots)
    parts = []
    for i, slot in enumerate(slots, start=1):
        delay_ms = int(round(slot.narration_start * 1000))
        parts.append(f"[{i}:a]aresample=48000,adelay={delay_ms}:all=1[n{i}]")
    mix_in = "".join(f"[n{i}]" for i in range(1, n + 1))
    parts.append(f"{mix_in}amix=inputs={n}:normalize=0:duration=longest,apad=whole_dur={total}[narr]")
    parts.append("[narr]asplit=2[narr_main][narr_sc]")
    fade_out = max(0.0, total - 3)
    parts.append(f"[{n + 1}:a]aresample=48000,lowpass=f=900,tremolo=f=0.15:d=0.3,"
                 f"afade=t=in:d=2,afade=t=out:st={fade_out}:d=3,volume=-10dB[pad]")
    parts.append(f"[pad][narr_sc]sidechaincompress=threshold={duck['threshold']}:ratio={duck['ratio']}:"
                 f"attack={duck['attack_ms']}:release={duck['release_ms']}[ducked]")
    parts.append(f"[narr_main][ducked]amix=inputs=2:normalize=0:duration=first,"
                 f"loudnorm=I={loudness['I']}:TP={loudness['TP']}:LRA=11,aresample=48000[aout]")
    parts.append(f"[0:v]subtitles={srt_name}:force_style='FontName=Arial,FontSize=18,MarginV=36,"
                 f"Outline=1,Shadow=0'[vout]")
    return ";".join(parts)


def build(ctx: Context) -> Path:
    narr = _narration(ctx)
    slots, total = timeline.build(ctx.sb, {k: v[1] for k, v in narr.items()})

    out_dir = ctx.paths.outputs / "final"
    out_dir.mkdir(parents=True, exist_ok=True)
    srt_name, mp4_name = f"{OUT_NAME}.srt", f"{OUT_NAME}.mp4"
    (out_dir / srt_name).write_text(subtitles.to_srt(subtitles.cues_for(slots)), encoding="utf-8")

    fps = ctx.sb["render"]["fps"]
    args = ["-f", "lavfi", "-i", f"color=c=black:s={SIZE}:r={fps}:d={total}"]
    for slot in slots:
        args += ["-i", str(narr[slot.shot_id][0].resolve())]
    args += ["-f", "lavfi", "-i", f"aevalsrc=exprs={PAD_EXPR}:s=48000:d={total}"]
    args += ["-filter_complex", filter_graph(slots, total, ctx.sb["mix"]["duck"], ctx.sb["mix"]["loudness"], srt_name),
             "-map", "[vout]", "-map", "[aout]", "-t", str(total),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(fps),
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", mp4_name]
    # Run inside the output folder so the subtitles filter gets a plain relative path
    # (Windows drive letters need awkward escaping inside FFmpeg filter graphs).
    ffmpeg.run(args, cwd=out_dir)

    out = out_dir / mp4_name
    print(f"[radio] {ctx.paths.rel(out)}  ({total:.1f}s, {len(slots)} lines, subtitles: {srt_name})")
    for slot in slots:
        print(f"  {slot.shot_id}  {slot.start:6.2f}s  +{slot.duration:5.2f}s  narration {slot.narration_s:.2f}s")
    return out
