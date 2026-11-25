"""Find and run FFmpeg / ffprobe. FFmpeg is deterministic: same inputs, same output."""
from __future__ import annotations

import glob
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


def duration(path: Path) -> float:
    cmd = [find("ffprobe"), "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise FFmpegError(f"ffprobe could not read {path}: {proc.stderr.strip()}")
    return float(proc.stdout.strip())
