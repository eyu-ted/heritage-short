"""Narration stage (with a fake TTS) and the radio cut (with real FFmpeg on synthetic audio)."""
import json
import math
import struct

import pytest

from pipeline import ffmpeg
from pipeline.__main__ import main
from pipeline.cache import Manifest
from pipeline.providers.gemini import AudioResult
from pipeline.retry import QuotaError


RATE = 8000


def _tone(seconds):
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / RATE)))
                    for i in range(int(seconds * RATE)))


def _silence(seconds):
    return b"\x00\x00" * int(seconds * RATE)


class FakeGemini:
    """Speaks each paragraph as a tone (length ~ characters), with long pauses between paragraphs."""
    calls = []
    fail_after = None  # raise QuotaError after this many successful calls

    def __init__(self, api_key):
        pass

    def tts(self, model, text, *, voice, style=None):
        if FakeGemini.fail_after is not None and len(FakeGemini.calls) >= FakeGemini.fail_after:
            raise QuotaError("429 RESOURCE_EXHAUSTED")
        FakeGemini.calls.append(text)
        paragraphs = text.split("\n\n")
        pcm = _silence(0.3)
        for n, para in enumerate(paragraphs):
            pcm += _tone(0.6 + len(para) / 25)
            if n < len(paragraphs) - 1:
                pcm += _silence(1.5)
        return AudioResult(pcm + _silence(0.3), RATE, f"audio/L16;rate={RATE}", 10, 20)


@pytest.fixture
def ready_repo(repo, monkeypatch):
    """Storyboard with Amharic lines filled in, TTS replaced by a fake."""
    sb = json.loads(repo.storyboard.read_text(encoding="utf-8"))
    for i, shot in enumerate(sb["shots"], start=1):
        shot["narration"]["am"] = f"የሙከራ መስመር ቁጥር {i}፤ " + "ቡና " * i  # lines of different lengths
    sb["narration_defaults"]["batch"] = False  # most tests exercise single mode; batch has its own tests
    repo.storyboard.write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr("pipeline.narration.Gemini", FakeGemini)
    FakeGemini.calls, FakeGemini.fail_after = [], None
    return repo


def _log(repo):
    return [json.loads(l) for l in repo.runs_log.read_text(encoding="utf-8").splitlines()]


def test_narration_blocked_until_amharic_written(blank_repo, capsys):
    assert main(["narration"], root=blank_repo.root) == 2
    assert "Amharic line is empty" in capsys.readouterr().err


def test_narration_makes_one_wav_per_shot_and_records_duration(ready_repo):
    assert main(["narration"], root=ready_repo.root) == 0
    assert len(FakeGemini.calls) == 10
    entry = Manifest(ready_repo).entry("narration", "s01")
    assert entry["meta"]["duration_s"] > 1.0
    assert (ready_repo.root / entry["path"]).exists()
    assert sum(1 for l in _log(ready_repo) if l["status"] == "ok") == 10


def test_second_run_calls_nothing_and_logs_cache_hits(ready_repo):
    main(["narration"], root=ready_repo.root)
    FakeGemini.calls = []
    assert main(["narration"], root=ready_repo.root) == 0
    assert FakeGemini.calls == []
    assert sum(1 for l in _log(ready_repo) if l["status"] == "cache_hit") == 10


def test_changing_one_line_regenerates_only_that_line(ready_repo):
    main(["narration"], root=ready_repo.root)
    sb = json.loads(ready_repo.storyboard.read_text(encoding="utf-8"))
    sb["shots"][6]["narration"]["am"] = "አንድ ጀበና።"
    ready_repo.storyboard.write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")
    FakeGemini.calls = []
    assert main(["narration"], root=ready_repo.root) == 0
    assert FakeGemini.calls == ["አንድ ጀበና።"]


def test_quota_stops_cleanly_and_keeps_finished_lines(ready_repo, monkeypatch, capsys):
    monkeypatch.setattr("pipeline.retry.time.sleep", lambda s: None)
    FakeGemini.fail_after = 4
    assert main(["narration"], root=ready_repo.root) == 3
    assert "rerun the same command" in capsys.readouterr().err
    m = Manifest(ready_repo)
    assert sum(1 for s in ("s01", "s02", "s03", "s04", "s05") if m.artifact("narration", s)) == 4

    FakeGemini.fail_after, FakeGemini.calls = None, []
    assert main(["narration"], root=ready_repo.root) == 0
    assert len(FakeGemini.calls) == 6  # only the missing lines


def _enable_batch(repo):
    sb = json.loads(repo.storyboard.read_text(encoding="utf-8"))
    sb["narration_defaults"]["batch"] = True
    repo.storyboard.write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")


def test_batch_mode_uses_one_request_for_all_lines(ready_repo):
    _enable_batch(ready_repo)
    assert main(["narration"], root=ready_repo.root) == 0
    assert len(FakeGemini.calls) == 1 and FakeGemini.calls[0].count("\n\n") == 9
    m = Manifest(ready_repo)
    durations = [m.entry("narration", f"s{i:02d}")["meta"]["duration_s"] for i in range(1, 11)]
    assert durations == sorted(durations)  # the fake's lines grow longer, so the cut must too
    assert all(m.entry("narration", f"s{i:02d}")["meta"]["mode"] == "batch" for i in range(1, 11))
    assert list((ready_repo.outputs / "narration").glob("batch__*.wav"))  # uncut take kept as evidence


def test_batch_then_one_changed_line_is_a_single_request(ready_repo):
    _enable_batch(ready_repo)
    main(["narration"], root=ready_repo.root)
    sb = json.loads(ready_repo.storyboard.read_text(encoding="utf-8"))
    sb["shots"][6]["narration"]["am"] = "አንድ ጀበና።"
    ready_repo.storyboard.write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")
    FakeGemini.calls = []
    assert main(["narration"], root=ready_repo.root) == 0
    assert FakeGemini.calls == ["አንድ ጀበና።"]  # the walkthrough demo: one line, one call


def test_implausible_batch_cut_falls_back_to_single_lines(ready_repo, monkeypatch):
    _enable_batch(ready_repo)

    def bad_split(pcm, rate, texts):
        raise __import__("pipeline.audio_split", fromlist=["SplitError"]).SplitError("ratio 9.0")

    monkeypatch.setattr("pipeline.narration.audio_split.split", bad_split)
    assert main(["narration"], root=ready_repo.root) == 0
    assert len(FakeGemini.calls) == 1 + 10  # the batch, then one request per line
    assert any(l["status"] == "fallback" for l in _log(ready_repo))


def test_offline_refuses_to_call(ready_repo, capsys):
    assert main(["narration", "--offline"], root=ready_repo.root) == 2
    assert FakeGemini.calls == []


def test_radio_needs_narration_first(ready_repo, capsys):
    assert main(["radio"], root=ready_repo.root) == 2


def _ffmpeg_available():
    try:
        ffmpeg.find("ffmpeg")
        return True
    except ffmpeg.FFmpegError:
        return False


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not installed")
def test_radio_cut_renders_with_expected_length(ready_repo):
    assert main(["narration"], root=ready_repo.root) == 0
    assert main(["radio"], root=ready_repo.root) == 0
    out = ready_repo.outputs / "final" / "radio_cut.mp4"
    srt = ready_repo.outputs / "final" / "radio_cut.srt"
    assert out.exists() and srt.exists()
    sb = json.loads(ready_repo.storyboard.read_text(encoding="utf-8"))
    srt_text = srt.read_text(encoding="utf-8")
    assert sb["shots"][0]["narration"]["en"].split()[0] in srt_text  # subtitles come from the storyboard
    from pipeline.timeline import build

    m = Manifest(ready_repo)
    _, total = build(sb, {s["id"]: m.entry("narration", s["id"])["meta"]["duration_s"] for s in sb["shots"]})
    assert abs(ffmpeg.duration(out) - total) < 0.3
