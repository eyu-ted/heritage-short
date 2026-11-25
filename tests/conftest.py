import json
import shutil
from pathlib import Path

import pytest

from pipeline.config import ROOT, get_paths


@pytest.fixture
def repo(tmp_path: Path):
    """A throwaway copy of the repo's contract files, so tests never touch real outputs/ or runs.jsonl."""
    (tmp_path / "schema").mkdir()
    shutil.copy(ROOT / "schema" / "storyboard.schema.json", tmp_path / "schema")
    shutil.copy(ROOT / "storyboard.json", tmp_path / "storyboard.json")
    return get_paths(tmp_path)


@pytest.fixture
def storyboard(repo):
    with open(repo.storyboard, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def blank_repo(repo):
    """The repo copy with every Amharic line emptied (the state before the script is written)."""
    sb = json.loads(repo.storyboard.read_text(encoding="utf-8"))
    for shot in sb["shots"]:
        shot["narration"]["am"] = ""
    repo.storyboard.write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")
    return repo
