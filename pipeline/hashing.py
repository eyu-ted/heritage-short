"""Cache keys.

A stage's output is named by a hash of everything that could change it
(prompt, seed, model, parameters, and the hashes of upstream files). Same
inputs -> same hash -> reuse the file. Any change -> new hash -> regenerate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HASH_LEN = 12
_FLOAT_DIGITS = 6


def _normalise(value: Any) -> Any:
    """Make equal-meaning values serialise identically (7 == 7.0, key order)."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        rounded = round(value, _FLOAT_DIGITS)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    raise TypeError(f"Cannot hash value of type {type(value).__name__}")


def canonical_json(obj: Any) -> str:
    return json.dumps(
        _normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def hash_inputs(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:HASH_LEN]


def hash_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:HASH_LEN]
