import json

from pipeline.cache import Manifest, artifact_path
from pipeline.jobs import Job


def _job(seed=1):
    return Job("keyframes", "s07", "png", {"prompt": "pour", "seed": seed})


def test_new_job_is_not_fresh(repo):
    assert not Manifest(repo).is_fresh(_job())


def test_recorded_job_is_fresh_and_persists(repo):
    job = _job()
    path = artifact_path(repo, job)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    Manifest(repo).record(job, path, meta={"w": 1344})

    reloaded = Manifest(repo)  # read back from disk
    assert reloaded.is_fresh(job)
    entry = reloaded.entry("keyframes", "s07")
    assert entry["path"] == f"outputs/keyframes/s07__{job.hash}.png"  # relative, forward slashes
    assert entry["meta"] == {"w": 1344}


def test_changed_inputs_are_not_fresh(repo):
    job = _job(seed=1)
    path = artifact_path(repo, job)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    m = Manifest(repo)
    m.record(job, path)
    assert not m.is_fresh(_job(seed=2))


def test_missing_file_is_not_fresh(repo):
    job = _job()
    path = artifact_path(repo, job)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    m = Manifest(repo)
    m.record(job, path)
    path.unlink()
    assert not m.is_fresh(job)
    assert m.artifact("keyframes", "s07") is None


def test_save_is_valid_json_and_leaves_no_temp_file(repo):
    job = _job()
    path = artifact_path(repo, job)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    Manifest(repo).record(job, path)
    json.loads(repo.manifest.read_text(encoding="utf-8"))
    assert not repo.manifest.with_suffix(".json.tmp").exists()


def test_artifact_path_contains_hash(repo):
    job = _job()
    assert artifact_path(repo, job).name == f"s07__{job.hash}.png"
