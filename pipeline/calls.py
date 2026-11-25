"""One way to call any model: time it, retry it, log every attempt to runs.jsonl."""
from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from .config import Paths
from .retry import classify, with_retry
from .runlog import Timer, log_event

T = TypeVar("T")


def logged_call(
    paths: Paths,
    fn: Callable[[], T],
    *,
    stage: str,
    provider: str,
    model: str,
    shot_id: str | None = None,
    params: dict[str, Any] | None = None,
    seed: int | None = None,
    input_hash: str | None = None,
    output: str | None = None,
    cost: Callable[[T], dict[str, Any] | None] | None = None,
    note: str | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    common = dict(stage=stage, shot_id=shot_id, provider=provider, model=model,
                  params=params, seed=seed, input_hash=input_hash, note=note)

    def attempt(n: int) -> T:
        timer = Timer()
        try:
            with timer:
                result = fn()
        except Exception as exc:  # noqa: BLE001 - classified and re-raised
            err = classify(exc)
            log_event(paths.runs_log, **common, status="error", attempt=n,
                      latency_ms=timer.ms, error=f"{type(err).__name__}: {err}"[:500])
            raise
        log_event(paths.runs_log, **common, status="ok", attempt=n, latency_ms=timer.ms,
                  output=output, cost=cost(result) if cost else None)
        return result

    return with_retry(attempt, attempts=attempts, sleep=sleep)
