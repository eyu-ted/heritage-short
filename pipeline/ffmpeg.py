"""Find and run FFmpeg / ffprobe. FFmpeg is deterministic: same inputs, same output."""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def find(name: str) -> str:
    """Locate a binary: env override, PATH, then the winget install folder (PATH may be stale)."""
    override = os.environ.get(f"{name.upper()}_BINARY")
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        pattern = os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "*", "bin", f"{name}.exe")
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    raise FFmpegError(f"{name} not found. Install FFmpeg (e.g. `winget install Gyan.FFmpeg`) "
                      f"or set {name.upper()}_BINARY.")


def run(args: list[str], cwd: Path | None = None) -> None:
    cmd = [find("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")


def loudness(path: Path, target_i: float = -14, target_tp: float = -1, target_lra: float = 11) -> dict:
    """Measure integrated loudness (LUFS), true peak (dBTP) and loudness range with FFmpeg's
    loudnorm analysis (EBU R128). Returns loudnorm's measurement dict, numbers as floats."""
    cmd = [find("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-vn",
           "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = proc.stderr
    start, end = text.rfind("{"), text.rfind("}")
    if proc.returncode != 0 or start < 0 or end < start:
        tail = "\n".join(text.strip().splitlines()[-10:])
        raise FFmpegError(f"loudness analysis failed for {path}:\n{tail}")
    raw = json.loads(text[start:end + 1])
    out: dict = {}
    for key, value in raw.items():
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            out[key] = value
    return out


def probe(path: Path) -> dict:
    """Duration, size, frame rate and codecs of a media file."""
    cmd = [find("ffprobe"), "-v", "error", "-show_entries",
           "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
           "-of", "json", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe could not read {path}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    info: dict = {"duration_s": round(float(data["format"]["duration"]), 3)}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and "video" not in info:
            num, den = (s.get("r_frame_rate") or "0/1").split("/")
            info["video"] = {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
                             "fps": round(float(num) / float(den or 1), 3)}
        elif s.get("codec_type") == "audio" and "audio" not in info:
            info["audio"] = {"codec": s.get("codec_name"), "sample_rate": int(s.get("sample_rate") or 0),
                             "channels": s.get("channels")}
    return info


def duration(path: Path) -> float:
    cmd = [find("ffprobe"), "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise FFmpegError(f"ffprobe could not read {path}: {proc.stderr.strip()}")
    return float(proc.stdout.strip())
