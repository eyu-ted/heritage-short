"""Phase 7: the final edit (real FFmpeg at a tiny size), the C2PA split (FAILURES F11) and
`all` not stopping on a missing score."""
import json
import math
import re
import struct
import wave

import pytest

from pipeline import assemble, ffmpeg, narration, subtitles, timeline
from pipeline.__main__ import main
from pipeline.cache import Manifest
from pipeline.config import get_paths
from pipeline.context import Context
from pipeline.jobs import Job
from pipeline.providers.gemini import split_c2pa
from pipeline.storyboard import load
from tests.test_phase4 import _sb, cf_repo, needs_ffmpeg, tiny  # noqa: F401  (fixtures)


def _c2pa_chunk(payload_len=64):
    """Same layout as Gemini TTS: b"C2PA" + uint32 LE size + a JUMBF box (size, b"jumb", ...)."""
    body = struct.pack(">I", payload_len) + b"jumb" + b"\x00\x00\x00\x1ejumdc2pa" + b"\x7f" * (payload_len - 20)
    assert len(body) == payload_len
    return b"C2PA" + struct.pack("<I", len(body)) + body, body


def _tone(n=4800):
    return b"".join(struct.pack("<h", int(8000 * math.sin(i / 7))) for i in range(n))


# ---- the C2PA credential is not audio ---------------------------------------------------

def test_split_c2pa_separates_the_credential_from_the_speech():
    pcm = _tone()
    chunk, body = _c2pa_chunk()
    speech, credential = split_c2pa(pcm + chunk)
    assert speech == pcm and credential == body


def test_split_c2pa_leaves_plain_audio_alone():
    pcm = _tone()
    assert split_c2pa(pcm) == (pcm, None)
    # the four bytes "C2PA" inside the samples, without the chunk structure, are just audio
    fake = pcm[:100] + b"C2PA" + pcm[100:]
    assert split_c2pa(fake) == (fake, None)


def test_repair_cuts_the_credential_out_of_recorded_lines(repo):
    paths = get_paths(repo.root)
    m = Manifest(paths)
    chunk, body = _c2pa_chunk()
    job = Job("narration", "s01", "wav", {"t": 1})
    wav_path = repo.outputs / "narration" / "s01__test.wav"
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(_tone() + chunk)
    m.record(job, wav_path, meta={"duration_s": 9.99, "voice": "v"})

    assert main(["narration", "--repair-c2pa"], root=repo.root) == 0
    entry = Manifest(paths).entry("narration", "s01")
    with wave.open(str(wav_path)) as w:
        assert w.readframes(w.getnframes()) == _tone()
    assert entry["meta"]["duration_s"] == round(4800 / 24000, 3)
    assert (repo.root / entry["meta"]["c2pa"]).read_bytes() == body
    log = [json.loads(line) for line in paths.runs_log.read_text(encoding="utf-8").splitlines()]
    assert log[-1]["model"] == "repair-c2pa" and log[-1]["params"]["removed_bytes"] == len(chunk)

    ctx = Context(paths=paths, sb=load(paths), manifest=Manifest(paths), force=False, offline=True, shot_ids=())
    assert narration.repair_c2pa(ctx) == []  # idempotent


# ---- picture timing -----------------------------------------------------------------------

def test_crossfades_start_on_each_shots_slot_and_the_film_keeps_its_length():
    slots = [timeline.Slot(f"s{i}", start, dur, start + 0.4, dur - 1, "x")
             for i, (start, dur) in enumerate([(0.0, 5.0), (5.0, 4.0), (9.0, 6.0)])]
    graph = assemble.picture_graph(slots, (64, 112), 24, crossfade_s=0.5, fade_s=1.0)
    offsets = [float(x) for x in re.findall(r"offset=([\d.]+)", ";".join(graph))]
    assert offsets == [5.0, 9.0, 15.0]  # next shot's start, then the end of the last shot
    lengths = [float(x) for x in re.findall(r"trim=duration=([\d.]+)", ";".join(graph))]
    assert lengths == [5.5, 4.5, 7.0]  # each shot covers the transition after it
    assert "fadeblack" in graph[-1]


def test_end_card_is_drawn_with_the_subtitles():
    card = subtitles.Card(80.0, 83.0, "Made with AI", "Buna - a Heritage Short")
    ass = subtitles.to_ass([], 1080, 1920, card)
    assert "Style: Card," in ass
    (event,) = [line for line in ass.splitlines() if line.startswith("Dialogue")]
    assert event.startswith("Dialogue: 1,0:01:20.00,0:01:23.00,Card")
    assert "Made with AI" in event and "Buna - a Heritage Short" in event and "\\fad(" in event


# ---- the whole edit ---------------------------------------------------------------------------

@pytest.fixture
def small_formats(monkeypatch):
    monkeypatch.setattr(assemble, "FORMATS", {"9x16": (72, 128), "16x9": (128, 72)})


@needs_ffmpeg
def test_assemble_makes_both_formats_on_target(tiny, small_formats, capsys):  # noqa: F811
    assert main(["shots"], root=tiny.root) == 0
    assert main(["assemble", "--offline"], root=tiny.root) == 0  # local work runs under --offline
    m = Manifest(tiny)
    sb = _sb(tiny)
    _, total = timeline.build(sb, {s["id"]: m.entry("narration", s["id"])["meta"]["duration_s"] for s in sb["shots"]})
    for fmt, size in (("9x16", [72, 128]), ("16x9", [128, 72])):
        entry = m.entry("assemble", f"film_{fmt}")
        info = ffmpeg.probe(tiny.root / entry["path"])
        assert abs(info["duration_s"] - total) < 0.15
        assert [info["video"]["width"], info["video"]["height"]] == size and info["video"]["fps"] == 24
        assert info["audio"]["codec"] == "aac" and info["audio"]["sample_rate"] == 48000
        meta = entry["meta"]
        assert abs(meta["lufs"] - sb["mix"]["loudness"]["I"]) <= 1.0
        assert meta["true_peak_dbtp"] <= sb["mix"]["loudness"]["TP"]
        assert meta["music"] == "placeholder" and meta["problems"] == []
    assert (tiny.outputs / "final" / "buna_en.srt").exists()
    assert "placeholder bed" in capsys.readouterr().out

    assert main(["assemble", "--dry-run"], root=tiny.root) == 0
    assert capsys.readouterr().out.count("cached") >= 2  # nothing changed -> nothing re-rendered


@needs_ffmpeg
def test_changing_a_subtitle_rebuilds_the_films_but_no_shot(tiny, small_formats, capsys):  # noqa: F811
    assert main(["shots"], root=tiny.root) == 0
    assert main(["assemble"], root=tiny.root) == 0
    sb = _sb(tiny)
    sb["shots"][3]["narration"]["en"] = "A different line."
    tiny.storyboard.write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    capsys.readouterr()
    assert main(["all", "--dry-run"], root=tiny.root) == 0
    rows = [line.split() for line in capsys.readouterr().out.splitlines()]
    would = {r[1] for r in rows if len(r) >= 4 and r[0] in ("shots", "assemble") and "would" in r}
    assert would == {"film_9x16", "film_16x9"}


@needs_ffmpeg
def test_all_continues_past_a_score_that_is_not_made_yet(tiny, small_formats, monkeypatch, capsys):  # noqa: F811
    """`all` must not stop at music (made on Kaggle): it notes it and assembles with the
    placeholder bed. (The fixture's fake narration is not a real TTS job, so `all` starts at shots.)"""
    monkeypatch.setattr("pipeline.__main__.STAGE_ORDER", ("shots", "music", "assemble"))
    assert main(["all", "--offline"], root=tiny.root) == 0
    out = capsys.readouterr().out
    assert "[music] continuing: the film uses the placeholder bed" in out
    assert Manifest(tiny).artifact("assemble", "film_9x16") is not None
    assert main(["music"], root=tiny.root) == 2  # on its own, the music stage still says what to do
