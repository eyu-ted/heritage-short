"""The manifest: which file is the current output for each (stage, key), and its hash.

outputs/manifest.json
{
  "version": 1,
  "stages": {
    "keyframes": {"s07": {"hash": "...", "path": "outputs/keyframes/s07__<hash>.png",
                           "status": "ok", "produced_at": "...", "meta": {...}}}
  }
}

A job is fresh (skip it) only when the manifest hash matches AND the file exists.
Output files carry the hash in their name, so old versions are never overwritten.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Paths
from .jobs import Job

MANIFEST_VERSION = 1


def artifact_path(paths: Paths, job: Job) -> Path:
    return paths.outputs / job.stage / f"{job.key}__{job.hash}.{job.ext}"


class Manifest:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.path = paths.manifest
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("version") != MANIFEST_VERSION:
                raise ValueError(f"Unsupported manifest version in {self.path}")
            return data
        return {"version": MANIFEST_VERSION, "stages": {}}

    def entry(self, stage: str, key: str) -> dict[str, Any] | None:
        return self.data["stages"].get(stage, {}).get(key)

    def artifact(self, stage: str, key: str) -> Path | None:
        """Current output file for (stage, key), or None if missing on disk."""
        entry = self.entry(stage, key)
        if not entry:
            return None
        path = self.paths.abs(entry["path"])
        return path if path.exists() else None

    def is_fresh(self, job: Job) -> bool:
        entry = self.entry(job.stage, job.key)
        return bool(
            entry
            and entry.get("hash") == job.hash
            and self.paths.abs(entry["path"]).exists()
        )

    def record(
        self,
        job: Job,
        path: Path,
        status: str = "ok",
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.data["stages"].setdefault(job.stage, {})[job.key] = {
            "hash": job.hash,
            "path": self.paths.rel(path),
            "status": status,
            "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "meta": meta or {},
        }
        self.save()

    def save(self) -> None:
        """Atomic write: a crash mid-write never leaves a half-written manifest."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self.path)
