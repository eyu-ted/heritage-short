"""A Job is one unit of work a stage may need to do (one shot, one music seed, the final film)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .hashing import hash_inputs


class NotReadyError(RuntimeError):
    """A stage cannot run yet because something upstream (or in the storyboard) is missing."""


@dataclass
class Job:
    stage: str
    key: str  # shot id ("s07"), music candidate ("score-seed11") or "film"
    ext: str  # output file extension
    inputs: dict[str, Any]  # everything that determines the output
    blocked: str | None = None  # why it cannot run yet (missing upstream), if so

    @property
    def hash(self) -> str:
        return hash_inputs({"stage": self.stage, "key": self.key, **self.inputs})
