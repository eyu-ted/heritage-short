import json

from PIL import Image

from pipeline.__main__ import main
from pipeline.cache import Manifest, artifact_path
from pipeline.keyframes import jobs as keyframe_jobs
from pipeline.shots import jobs as shot_jobs
from pipeline.storyboard import load


def test_validate_ok(blank_repo, capsys):
    assert main(["validate"], root=blank_repo.root) == 0
    out = capsys.readouterr().out
    assert "is valid" in out
    assert "not ready for narration" in out  # Amharic not written yet


def test_invalid_storyboard_exit_code(repo, capsys):
    sb = json.loads(repo.storyboard.read_text(encoding="utf-8"))
    del sb["shots"][0]["reason"]
    repo.storyboard.write_text(json.dumps(sb), encoding="utf-8")
    assert main(["validate"], root=repo.root) == 1


def test_dry_run_lists_every_shot(repo, capsys):
    assert main(["all", "--dry-run"], root=repo.root) == 0
    out = capsys.readouterr().out
    for i in range(1, 11):
        assert f"keyframes  s{i:02d}" in out
    assert "blocked" in out  # narration and shots wait for upstream work


def test_dry_run_single_shot(repo, capsys):
    assert main(["keyframes", "--dry-run", "--shot", "s07"], root=repo.root) == 0
    out = capsys.readouterr().out
    assert "s07" in out and "s06" not in out


def test_unknown_shot_rejected(repo, capsys):
    assert main(["keyframes", "--dry-run", "--shot", "s99"], root=repo.root) == 1


def test_assemble_waits_for_its_inputs(repo, capsys):
    assert main(["assemble"], root=repo.root) == 2  # no narration or shots yet
    assert "blocked" in capsys.readouterr().err


def test_music_not_made_yet_points_to_kaggle(repo, capsys):
    assert main(["music"], root=repo.root) == 2
    assert "python -m pipeline export music" in capsys.readouterr().err


def _fake_keyframe(repo, sb, manifest, job, colour):
    path = artifact_path(repo, job)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), colour).save(path)
    manifest.record(job, path)


def _rows(out):
    """Parse the dry-run table into {key: status} for data rows only."""
    rows = {}
    for line in out.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4 and parts[0] in {"narration", "keyframes", "shots", "music", "assemble"}:
            rows[parts[1]] = parts[3]
    return rows


def test_only_changed_shot_is_invalidated(refs_repo, capsys):
    """The walkthrough promise: change one prompt -> only that shot regenerates."""
    repo = refs_repo
    sb = load(repo)
    manifest = Manifest(repo)
    for job in keyframe_jobs(sb, manifest):
        _fake_keyframe(repo, sb, manifest, job, "black")

    assert main(["keyframes", "--dry-run"], root=repo.root) == 0
    rows = _rows(capsys.readouterr().out)
    assert len(rows) == 10 and set(rows.values()) == {"cached"}

    sb["shots"][6]["keyframe"]["prompt"] += " Golden hour."
    repo.storyboard.write_text(json.dumps(sb), encoding="utf-8")
    assert main(["keyframes", "--dry-run"], root=repo.root) == 0
    rows = _rows(capsys.readouterr().out)
    assert [k for k, v in rows.items() if v == "would run"] == ["s07"]


def test_new_keyframe_changes_its_shot_hash_only(refs_repo):
    repo = refs_repo
    sb = load(repo)
    manifest = Manifest(repo)
    for job in keyframe_jobs(sb, manifest):
        _fake_keyframe(repo, sb, manifest, job, "black")
    before = {j.key: j.hash for j in shot_jobs(sb, manifest)}

    s07 = next(j for j in keyframe_jobs(sb, manifest) if j.key == "s07")
    Image.new("RGB", (8, 8), "white").save(artifact_path(repo, s07))  # new picture, same name
    after = {j.key: j.hash for j in shot_jobs(sb, Manifest(repo))}

    changed = [k for k in before if before[k] != after[k]]
    assert changed == ["s07"]
