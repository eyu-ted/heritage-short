"""runs.jsonl: one JSON line per model call (and per cache hit / fallback).

This file is the evidence for COSTS.md, EXPERIMENTS.md and FAILURES.md,
so every call goes through `log_event`, and secrets are scrubbed first.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_ID = os.environ.get("HERITAGE_RUN_ID") or (
    datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
)

FIELDS = (
    "stage", "shot_id", "provider", "model", "params", "seed", "input_hash",
    "output", "latency_ms", "status", "attempt", "error", "cost", "gpu_minutes",
    "note",
)
STATUSES = {"ok", "error", "cache_hit", "fallback", "skipped"}
_SECRET_MARKERS = ("api_key", "apikey", "token", "secret", "authorization", "password")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: "***" if any(m in str(k).lower() for m in _SECRET_MARKERS) else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def log_event(path: Path | str, **fields: Any) -> dict[str, Any]:
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unknown run-log fields: {sorted(unknown)}")
    status = fields.get("status")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}, got {status!r}")

    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run_id": RUN_ID,
    }
    for name in FIELDS:
        record[name] = _redact(fields.get(name))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


class Timer:
    """with Timer() as t: ...  ->  t.ms is the elapsed wall time in milliseconds."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = int(round((time.perf_counter() - self._start) * 1000))
