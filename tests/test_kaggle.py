"""Phase 5/6: the Kaggle hand-off (export a notebook, ingest its outputs) and what uses them.
No network and no GPU: the "notebook outputs" are tiny files made here with FFmpeg / wave."""
import ast
import contextlib
import io
import json
import math
import struct
import wave
import zipfile

import pytest

from pipeline import ffmpeg, kaggle, music, shots
from pipeline.__main__ import main
from pipeline.cache import Manifest
from tests.test_phase4 import FakeCloudflare, _sb, cf_repo, needs_ffmpeg, tiny  # noqa: F401 (fixtures)


def _exported_jobs(repo, notebook):
    name = "wan" if notebook.startswith("wan") else "music"
    folder = repo.root / "kaggle" / "build" / name
    meta = json.loads((folder / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert meta["is_private"] is True and meta["code_file"] == notebook and meta["enable_internet"]
    nb = json.loads((folder / notebook).read_text(encoding="utf-8"))
    cell = next("".join(c["source"]) for c in nb["cells"] if "".join(c["source"]).startswith("JOBS = "))
    return ast.literal_eval(cell[len("JOBS = "):].split("  # filled")[0])


def _fake_clip(path, seconds=2.0, size=64):
    ffmpeg.run(["-f", "lavfi", "-i", f"testsrc=size={size}x{size}:rate=24:duration={seconds}",
                "-pix_fmt", "yuv420p", str(path)])


def _fake_wav(path, seconds=3.0, rate=8000):
    pcm = b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 330 * i / rate)))
                   for i in range(int(seconds * rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate), w.writeframes(pcm)


def _sidecar(folder, item, ext, status="ok", **extra):
    name = f"{item['key']}__{item['hash']}"
    side = {"key": item["key"], "hash": item["hash"], "status": status, "file": f"{name}.{ext}",
            "seconds": 600.0, "gpu": "Tesla T4", "settings": {"steps": 30}, **extra}
    (folder / f"{name}.json").write_text(json.dumps(side), encoding="utf-8")
    return folder / f"{name}.{ext}"


def _runs(repo):
    return [json.loads(line) for line in repo.runs_log.read_text(encoding="utf-8").splitlines()]


# ---- the notebook builder ----------------------------------------------------------------

def test_percent_script_becomes_a_notebook_with_the_jobs_inside():
    src = "# %% [markdown]\n# # Title\n# text\n\n# %%\nJOBS = None  # filled\n\n# %%\nprint(len(JOBS))\n"
    jobs = [{"key": "s07", "hash": "abc", "seed": 1, "ok": True, "key2": None}]
    nb = kaggle.notebook_from_percent(src, jobs)
    kinds = [c["cell_type"] for c in nb["cells"]]
    assert kinds == ["markdown", "code", "code"]
    assert "".join(nb["cells"][0]["source"]) == "# Title\ntext"
    scope = {}
    exec("".join(nb["cells"][1]["source"]), scope)  # valid Python (True/None, not JSON true/null)
    assert scope["JOBS"] == jobs


def test_both_notebook_sources_parse_as_python():
    for target in kaggle.TARGETS.values():
        source = (kaggle.ROOT / "notebooks" / target.notebook).read_text(encoding="utf-8")
        assert kaggle.JOBS_LINE in source
        for cell in kaggle.notebook_from_percent(source, [{"key": "x"}])["cells"]:
            if cell["cell_type"] == "code":
                ast.parse("".join(cell["source"]))


def test_clip_hash_ignores_the_shot_length_but_the_master_does_not(storyboard):
    shot = next(s for s in storyboard["shots"] if s["id"] == "s07")
    a = shots.clip_inputs(storyboard, shot, "kf")
    shot["min_duration_s"] = 12
    assert shots.clip_inputs(storyboard, shot, "kf") == a  # re-timing never costs GPU time
    assert a["size"] % 32 == 0 and (a["frames"] - 1) % 4 == 0


# ---- export ------------------------------------------------------------------------------

def test_export_wan_embeds_only_the_jobs_not_made_yet(tiny):
    assert main(["export", "wan"], root=tiny.root) == 0
    jobs = _exported_jobs(tiny, "wan_shots.ipynb")
    assert [j["key"] for j in jobs] == ["s03", "s07", "s10"]  # the wan shots
    assert all(j["image_b64"] and j["hash"] for j in jobs)
    assert main(["export", "wan", "--shot", "s07"], root=tiny.root) == 0
    assert [j["key"] for j in _exported_jobs(tiny, "wan_shots.ipynb")] == ["s07"]


def test_export_music_has_three_seeds(repo):
    assert main(["export", "music"], root=repo.root) == 0
    jobs = _exported_jobs(repo, "ace_step_music.ipynb")
    assert [j["seed"] for j in jobs] == [11, 22, 33] and all(j["thinking"] is False for j in jobs)


def test_export_needs_a_target(repo):
    assert main(["export"], root=repo.root) == 1


# ---- ingest wan + shots ----------------------------------------------------------------------

@needs_ffmpeg
def test_ingested_clip_replaces_the_fallback_and_is_retimed(tiny, tmp_path):
    assert main(["shots", "--shot", "s03"], root=tiny.root) == 0
    assert Manifest(tiny).entry("shots", "s03")["status"] == "fallback"

    main(["export", "wan", "--shot", "s03"], root=tiny.root)
    (item,) = _exported_jobs(tiny, "wan_shots.ipynb")
    dl = tmp_path / "download" / "out"
    dl.mkdir(parents=True)
    _fake_clip(_sidecar(dl, item, "mp4"))
    assert main(["ingest", "wan", "--from", str(dl.parent)], root=tiny.root) == 0

    clip_entry = Manifest(tiny).entry("clips", "s03")
    assert clip_entry["hash"] == item["hash"] and clip_entry["meta"]["gpu"] == "Tesla T4"
    line = [r for r in _runs(tiny) if r["provider"] == "kaggle"][-1]
    assert line["gpu_minutes"] == 10.0 and line["status"] == "ok" and line["stage"] == "clips"

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["shots", "--dry-run", "--shot", "s03"], root=tiny.root)
    assert "would run" in out.getvalue()  # the fallback is stale now that the real clip exists

    assert main(["shots", "--shot", "s03"], root=tiny.root) == 0
    entry = Manifest(tiny).entry("shots", "s03")
    assert entry["status"] == "ok" and entry["meta"]["render"] == "wan"
    assert entry["meta"]["slowdown"] == shots.MAX_SLOWDOWN  # 2 s clip into a 3 s+ slot... capped
    master = Manifest(tiny).artifact("shots", "s03")
    assert abs(ffmpeg.duration(master) - entry["meta"]["duration_s"]) < 0.1


@needs_ffmpeg
def test_stale_failed_and_zipped_outputs(tiny, tmp_path):
    main(["export", "wan"], root=tiny.root)
    s03, s07, s10 = _exported_jobs(tiny, "wan_shots.ipynb")
    dl = tmp_path / "out"
    dl.mkdir()
    _fake_clip(_sidecar(dl, s03, "mp4"))
    _fake_clip(_sidecar(dl, {**s07, "hash": "0123456789ab"}, "mp4"))  # made from other inputs
    _sidecar(dl, s10, "mp4", status="error", error="OutOfMemoryError: CUDA out of memory")
    archive = tmp_path / "out.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for f in dl.iterdir():
            zf.write(f, f"out/{f.name}")

    report = kaggle.ingest(_ctx(tiny), "wan", archive)
    assert report["ingested"] == ["s03"] and report["stale"] == ["s07"] and report["failed"] == ["s10"]
    assert Manifest(tiny).entry("clips", "s07") is None
    errors = [r for r in _runs(tiny) if r["provider"] == "kaggle" and r["status"] == "error"]
    assert "out of memory" in errors[-1]["error"]
    again = kaggle.ingest(_ctx(tiny), "wan", archive)
    assert again["already"] == ["s03"]


def _ctx(repo):
    from pipeline.context import Context
    from pipeline.storyboard import load

    return Context(paths=repo, sb=load(repo), manifest=Manifest(repo))


# ---- music ---------------------------------------------------------------------------------

@needs_ffmpeg
def test_music_ingest_pick_and_audition(tiny, tmp_path):
    main(["export", "music"], root=tiny.root)
    items = _exported_jobs(tiny, "ace_step_music.ipynb")
    dl = tmp_path / "out"
    dl.mkdir()
    for item in items:
        _fake_wav(_sidecar(dl, item, "wav"))
    assert main(["ingest", "music", "--from", str(dl)], root=tiny.root) == 0
    assert main(["music"], root=tiny.root) == 0  # all three candidates cached now

    assert main(["music", "--pick", "score-seed99"], root=tiny.root) == 1
    assert main(["music", "--pick", "score-seed22"], root=tiny.root) == 0
    assert _sb(tiny)["music"]["chosen"] == "score-seed22"

    assert main(["radio", "--music", "score-seed11"], root=tiny.root) == 0
    assert (tiny.outputs / "final" / "radio_cut__score-seed11.mp4").exists()


def test_music_hash_includes_the_generation_settings(storyboard):
    a = music.jobs(storyboard, None)[0]
    assert a.inputs["variant"] == music.ACE["variant"] and a.inputs["steps"] == music.ACE["steps"]
