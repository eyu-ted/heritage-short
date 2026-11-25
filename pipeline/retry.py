"""Retries with backoff, and a small vocabulary for failures.

Every provider error is classified into one of four kinds, because each one
needs a different response:

  TransientError   network blip, 5xx, timeout      -> retry with backoff
  QuotaError       429 / rate limit / daily quota  -> retry slower, then give up and log
  BadInputError    4xx we caused (bad prompt/args) -> fail fast, retrying will not help
  OutOfMemoryError GPU ran out of memory           -> fail fast, caller lowers resolution or falls back
"""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")


class StageError(RuntimeError):
    """Base class for classified pipeline failures."""


class TransientError(StageError):
    pass


class QuotaError(StageError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class BadInputError(StageError):
    pass


class OutOfMemoryError(StageError):
    pass


RETRYABLE = (TransientError, QuotaError)


def classify(exc: BaseException) -> StageError:
    """Turn any exception into one of the StageError kinds."""
    if isinstance(exc, StageError):
        return exc
    text = str(exc).lower()
    if "out of memory" in text or "cuda oom" in text:
        return OutOfMemoryError(str(exc))
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            retry_after = exc.response.headers.get("retry-after")
            try:
                seconds = float(retry_after) if retry_after else None
            except ValueError:
                seconds = None
            return QuotaError(f"HTTP 429: {exc}", seconds)
        if code >= 500:
            return TransientError(f"HTTP {code}: {exc}")
        return BadInputError(f"HTTP {code}: {exc}")
    # SDK errors (e.g. google.genai.errors.APIError) carry the HTTP status as an int `code`.
    # Found in the Phase 2 smoke test: a Gemini 503 "high demand" was misread as bad input.
    sdk_code = getattr(exc, "code", None)
    if isinstance(sdk_code, int) and 400 <= sdk_code < 600:
        if sdk_code == 429:
            return QuotaError(f"HTTP 429: {exc}")
        if sdk_code >= 500:
            return TransientError(f"HTTP {sdk_code}: {exc}")
        return BadInputError(f"HTTP {sdk_code}: {exc}")
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, ConnectionError, TimeoutError)):
        return TransientError(str(exc))
    if "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return QuotaError(str(exc))
    return BadInputError(f"{type(exc).__name__}: {exc}")


def with_retry(
    fn: Callable[[int], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    on_error: Callable[[int, StageError], None] | None = None,
) -> T:
    """Call fn(attempt) until it succeeds or the error is not worth retrying.

    fn receives the 1-based attempt number so it can log it.
    on_error(attempt, error) is called for every failed attempt (for logging).
    Raises the classified StageError after the last attempt.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    for attempt in range(1, attempts + 1):
        try:
            return fn(attempt)
        except Exception as raw:  # noqa: BLE001 - we classify everything
            err = classify(raw)
            if on_error:
                on_error(attempt, err)
            if not isinstance(err, RETRYABLE) or attempt == attempts:
                raise err from raw
            delay = min(max_delay, base_delay * 2 ** (attempt - 1))
            if isinstance(err, QuotaError):
                delay = max(delay * 2, err.retry_after or 0)
            sleep(delay + random.uniform(0, delay * 0.25))
    raise AssertionError("unreachable")
