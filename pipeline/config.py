"""Paths, stage order and secret loading.

Everything that touches the filesystem asks `get_paths()` for locations, so
tests can point the whole pipeline at a temporary folder.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The order the stages run in. Each name matches a module in pipeline/.
STAGE_ORDER = ("narration", "keyframes", "shots", "music", "assemble")


class MissingSecretError(RuntimeError):
    """A required key is not in the environment or .env."""


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def storyboard(self) -> Path:
        return self.root / "storyboard.json"

    @property
    def schema(self) -> Path:
        return self.root / "schema" / "storyboard.schema.json"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def manifest(self) -> Path:
        return self.outputs / "manifest.json"

    @property
    def runs_log(self) -> Path:
        return self.root / "runs.jsonl"

    def rel(self, path: Path) -> str:
        """Path relative to the repo root, with forward slashes (portable in git)."""
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return Path(path).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root / rel


def get_paths(root: Path | str | None = None) -> Paths:
    return Paths(Path(root) if root is not None else ROOT)


def load_env(paths: Paths) -> None:
    """Load .env into the process environment without overriding real env vars."""
    from dotenv import load_dotenv

    load_dotenv(paths.root / ".env", override=False)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingSecretError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value
