"""Reference sheet, keyframes (fake Cloudflare) and Ken Burns shots / animatic (real FFmpeg, tiny size)."""
import io
import json
import math
import struct
import wave

import pytest
from PIL import Image

from pipeline import ffmpeg, shots
from pipeline.__main__ import main
from pipeline.cache import Manifest
from pipeline.jobs import Job


class FakeCloudflare:
    calls = []

    def __init__(self, account, token):
        pass

    def image(self, model, prompt, **kw):
        FakeCloudflare.calls.append({"model": model, "prompt": prompt, **kw})
        shade = (len(FakeCloudflare.calls) * 37) % 255  # every call returns a different picture
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (shade, 90, 40)).save(buf, format="JPEG")
        return buf.getvalue()


@pytest.fixture
def cf_repo(repo, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-for-tests")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-for-tests")
    monkeypatch.setattr("pipeline.refs.Cloudflare", FakeCloudflare)
    monkeypatch.setattr("pipeline.keyframes.Cloudflare", FakeCloudflare)
    FakeCloudflare.calls = []
    return repo


def _sb(repo):
    return json.loads(repo.storyboard.read_text(encoding="utf-8"))


def _save(repo, sb):
    repo.storyboard.write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_all(repo):
    assert main(["refs", "--options", "2"], root=repo.root) == 0
    for ref in ("jebena", "sini", "figure"):
        assert main(["refs", "--pick", f"{ref}=1"], root=repo.root) == 0


# ---- reference sheet ---------------------------------------------------------

def test_refs_make_options_once(cf_repo):
    assert main(["refs", "--options", "2"], root=cf_repo.root) == 0
    assert len(FakeCloudflare.calls) == 3 * 2
    FakeCloudflare.calls = []
    assert main(["refs", "--options", "2"], root=cf_repo.root) == 0
    assert FakeCloudflare.calls == []  # cached


def test_pick_writes_the_reference_into_the_storyboard(cf_repo):
    main(["refs", "--options", "2"], root=cf_repo.root)
    assert main(["refs", "--pick", "jebena=2"], root=cf_repo.root) == 0
    image = next(r for r in _sb(cf_repo)["references"] if r["id"] == "jebena")["image"]
    assert image.startswith("outputs/refs/jebena-opt2__") and (cf_repo.root / image).exists()


def test_bad_pick_is_refused(cf_repo, capsys):
    main(["refs", "--options", "2"], root=cf_repo.root)
    assert main(["refs", "--pick", "jebena=9"], root=cf_repo.root) == 1
    assert main(["refs", "--pick", "nonsense"], root=cf_repo.root) == 1


# ---- keyframes -----------------------------------------------------------------

def test_shots_without_references_run_while_others_wait(cf_repo, capsys):
    assert main(["keyframes"], root=cf_repo.root) == 2  # some shots are blocked...
    made = {c["prompt"][:30] for c in FakeCloudflare.calls}
    assert len(FakeCloudflare.calls) == 5  # ...but s01-s05 (no references) were generated
    assert "no approved image" in capsys.readouterr().err
    assert made


def test_keyframes_send_approved_references_small(cf_repo):
    _pick_all(cf_repo)
    FakeCloudflare.calls = []
    assert main(["keyframes", "--shot", "s07"], root=cf_repo.root) == 0
    (call,) = FakeCloudflare.calls
    assert len(call["refs"]) == 2 and call["width"] == 1536 and call["height"] == 1536
    assert "jebena (image 1)" in call["prompt"] and "sini (image 2)" in call["prompt"]
    for data in call["refs"]:
        assert max(Image.open(io.BytesIO(data)).size) <= 512


def test_take_bump_regenerates_one_shot_and_keeps_the_old_take(cf_repo):
    _pick_all(cf_repo)
    assert main(["keyframes"], root=cf_repo.root) == 0
    old = Manifest(cf_repo).artifact("keyframes", "s07")
    sb = _sb(cf_repo)
    next(s for s in sb["shots"] if s["id"] == "s07")["keyframe"]["take"] = 2
    _save(cf_repo, sb)
    FakeCloudflare.calls = []
    assert main(["keyframes"], root=cf_repo.root) == 0
    assert len(FakeCloudflare.calls) == 1
    assert old.exists() and Manifest(cf_repo).artifact("keyframes", "s07") != old


def test_repicking_a_reference_regenerates_exactly_the_shots_that_use_it(cf_repo):
    _pick_all(cf_repo)
    assert main(["keyframes"], root=cf_repo.root) == 0
    assert main(["refs", "--pick", "sini=2"], root=cf_repo.root) == 0
    FakeCloudflare.calls = []
    assert main(["keyframes"], root=cf_repo.root) == 0
    assert len(FakeCloudflare.calls) == 3  # s07, s08, s09 use sini


# ---- Ken Burns shots and the animatic (real FFmpeg, tiny) ----------------------------

def _ffmpeg_available():
    try:
        ffmpeg.find("ffmpeg")
        return True
    except ffmpeg.FFmpegError:
        return False


needs_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not installed")


def _fake_narration(repo, seconds=2.0):
    m = Manifest(repo)
    rate = 8000
    pcm = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 200 * i / rate)))
                   for i in range(int(seconds * rate)))
    for shot in _sb(repo)["shots"]:
        job = Job("narration", shot["id"], "wav", {"t": shot["id"]})
        path = repo.outputs / "narration" / f"{shot['id']}__test.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate), w.writeframes(pcm)
        m.record(job, path, meta={"duration_s": seconds})


@pytest.fixture
def tiny(cf_repo, monkeypatch):
    monkeypatch.setattr(shots, "MASTER", 96)  # keep renders fast
    sb = _sb(cf_repo)
    for s in sb["shots"]:
        s["min_duration_s"] = 3  # short shots (total must stay >= 60 s for the schema)
    sb["shots"][0]["min_duration_s"] = 15
    for s in sb["shots"][1:7]:
        s["min_duration_s"] = 6
    _save(cf_repo, sb)
    _pick_all(cf_repo)
    assert main(["keyframes"], root=cf_repo.root) == 0
    _fake_narration(cf_repo)
    return cf_repo


@needs_ffmpeg
def test_kenburns_shot_has_the_slot_length_and_master_size(tiny):
    assert main(["shots", "--shot", "s02"], root=tiny.root) == 0
    clip = Manifest(tiny).artifact("shots", "s02")
    assert abs(ffmpeg.duration(clip) - 6.0) < 0.1


@needs_ffmpeg
def test_wan_shot_falls_back_to_kenburns_and_stays_cached_until_inputs_change(tiny):
    assert main(["shots", "--shot", "s03"], root=tiny.root) == 0  # s03 is a wan shot
    entry = Manifest(tiny).entry("shots", "s03")
    assert entry["status"] == "fallback" and entry["meta"]["render"] == "kenburns"

    def plan():
        main(["shots", "--dry-run", "--shot", "s03"], root=tiny.root)

    from io import StringIO
    import contextlib
    out = StringIO()
    with contextlib.redirect_stdout(out):
        plan()
    assert "cached" in out.getvalue().splitlines()[2]

    _fake_narration(tiny, seconds=9.0)  # a longer line changes the fallback's duration
    out = StringIO()
    with contextlib.redirect_stdout(out):
        plan()
    assert "would run" in out.getvalue().splitlines()[2]


@needs_ffmpeg
def test_animatic_renders_vertical_with_full_length(tiny):
    assert main(["shots"], root=tiny.root) == 0
    assert main(["animatic"], root=tiny.root) == 0
    out = tiny.outputs / "final" / "animatic_9x16.mp4"
    sb = _sb(tiny)
    from pipeline.timeline import build

    _, total = build(sb, {s["id"]: 2.0 for s in sb["shots"]})
    assert abs(ffmpeg.duration(out) - total) < 0.3


def test_zoompan_pans_are_distinct():
    f = {p: shots.zoompan_filter(1.08, p, 48, 96, 24) for p in ("none", "left", "right", "up", "down")}
    assert len(set(f.values())) == 5
    assert "s=96x96" in f["none"] and "fps=24" in f["none"]
