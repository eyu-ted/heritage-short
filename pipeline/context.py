"""Everything a stage needs to run, passed as one object."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cache import Manifest
from .config import Paths


@dataclass
class Context:
    paths: Paths
    sb: dict[str, Any]
    manifest: Manifest
    force: bool = False  # ignore the cache and regenerate
    offline: bool = False  # never call a provider; use cache or fail clearly
    shot_ids: tuple[str, ...] = ()  # limit shot-based stages to these shots (empty = all)
