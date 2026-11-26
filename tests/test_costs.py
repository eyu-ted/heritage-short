import json
from datetime import datetime, timezone

import pytest

from pipeline import costs
from pipeline.__main__ import main

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def _event(**kw):
    base = {k: None for k in ("stage", "shot_id", "provider", "model", "params", "seed", "input_hash", "output",
                              "latency_ms", "status", "attempt", "error", "cost", "gpu_minutes", "note")}
    base.update(ts="2026-11-25T10:00:00.000+00:00", run_id="r1")
    base.update(kw)
    return base


EVENTS = [
    # narration: one TTS call that hit a quota error, then succeeded; later two cache hits
    _event(stage="narration", shot_id="s01", provider="gemini", model="gemini-3.8-flash-lite-tts",
           status="error", attempt=1, latency_ms=200, error="QuotaError: HTTP 429: RESOURCE_EXHAUSTED"),
    _event(stage="narration", shot_id="s01", provider="gemini", model="gemini-3.8-flash-lite-tts",
           status="ok", attempt=2, latency_ms=3000, input_hash="aaa", output="outputs/narration/s01__aaa.wav",
           cost={"unit": "tokens", "input": 1_000_000, "output": 1_000_000, "audio_s": 8.0}),
    _event(stage="narration", shot_id="s01", model="gemini-3.8-flash-lite-tts", status="cache_hit",
           input_hash="aaa", output="outputs/narration/s01__aaa.wav", run_id="r2"),
    _event(stage="narration", shot_id="s01", model="gemini-3.8-flash-lite-tts", status="cache_hit",
           input_hash="aaa", output="outputs/narration/s01__aaa.wav", run_id="r3"),
    _event(stage="narration", provider="gemini", model="gemini-3.8-flash-lite-tts", status="fallback",
           note="batch split rejected"),
    # keyframe: 1536x1536 (9 output tiles) with 2 reference images
    _event(stage="keyframes", shot_id="s07", provider="cloudflare", model="@cf/black-forest-labs/flux-2-klein-4b",
           status="ok", attempt=1, latency_ms=8000, input_hash="kkk", output="outputs/keyframes/s07__kkk.jpg",
           params={"size": [1536, 1536], "take": 1, "refs": ["jebena", "sini"]}),
    # a Kaggle job that ran out of memory after 6 GPU seconds, and one that worked
    _event(stage="clips", shot_id="s07", provider="kaggle", model="Wan", status="error", latency_ms=6000,
           gpu_minutes=0.1, error="OutOfMemoryError: CUDA out of memory"),
    _event(stage="music", shot_id="score-seed11", provider="kaggle", model="ACE", status="ok", latency_ms=12000,
           gpu_minutes=0.2, input_hash="mmm", output="outputs/music/score-seed11__mmm.wav"),
    # local FFmpeg work, and a cache hit nobody produced
    _event(stage="shots", shot_id="s07", provider="local", model="ffmpeg-zoompan", status="fallback",
           latency_ms=4000, input_hash="sss", output="outputs/shots/s07__sss-kenburns.mp4"),
    _event(stage="assemble", shot_id="film_9x16", status="cache_hit", input_hash="zzz"),
]


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "runs.jsonl"
    lines = [json.dumps(e) for e in EVENTS] + ["", "{not json"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _report(log, **kw):
    events, n, bad = costs.read_log(log)
    return costs.build_report(events, line_count=n, bad_lines=bad, now=NOW, **kw), events, n, bad


def test_read_log_counts_lines_and_skips_bad_ones(log):
    events, n, bad = costs.read_log(log)
    assert (len(events), n, bad) == (len(EVENTS), len(EVENTS) + 2, 1)


def test_missing_log_is_an_empty_report(tmp_path):
    events, n, bad = costs.read_log(tmp_path / "nope.jsonl")
    text = costs.build_report(events, line_count=n, bad_lines=bad, now=NOW)
    assert "0 lines, 0 events" in text and "Money actually spent: $0" in text


def test_cache_hits_are_attributed_by_input_hash(log):
    events, _, _ = costs.read_log(log)
    attributed, unmatched = costs.attribute(events)
    hits = [e for e in attributed if e["status"] == "cache_hit" and e["stage"] == "narration"]
    assert {e["provider"] for e in hits} == {"gemini"}
    assert unmatched == 1  # the assemble hit has no producing event in this log


def test_groups_count_statuses_latency_and_units(log):
    events, _, _ = costs.read_log(log)
    groups = {(g.stage, g.model): g for g in costs.group_events(costs.attribute(events)[0])}
    tts = groups[("narration", "gemini-3.8-flash-lite-tts")]
    assert (tts.counts["ok"], tts.counts["error"], tts.counts["cache_hit"], tts.counts["fallback"]) == (1, 1, 2, 1)
    assert sum(tts.latencies) == 3200 and tts.units["audio s"] == 8.0
    assert tts.unpriced == 0  # the fallback marker is not a call
    kf = groups[("keyframes", "@cf/black-forest-labs/flux-2-klein-4b")]
    assert kf.units["output tiles"] == 9 and kf.units["ref-image tiles"] == 2
    assert groups[("clips", "Wan")].units["GPU s"] == pytest.approx(6.0)


def test_list_price_estimates(log):
    events, _, _ = costs.read_log(log)
    by_status = {(e["stage"], e["status"]): e for e in events}
    # 1M input tokens at $0.50 + 1M output tokens at $6.00
    assert costs.estimate_usd(by_status[("narration", "ok")]) == pytest.approx(6.50)
    assert costs.estimate_usd(by_status[("narration", "error")]) == 0.0  # failed requests are not billed
    p_in, p_out = costs.TILE_PRICES["@cf/black-forest-labs/flux-2-klein-4b"]
    assert costs.estimate_usd(by_status[("keyframes", "ok")]) == pytest.approx(9 * p_out + 2 * p_in)
    # a failed GPU job still used GPU time
    assert costs.estimate_usd(by_status[("clips", "error")]) == pytest.approx(0.1 / 60 * costs.GPU_HOUR_USD)
    assert costs.estimate_usd(by_status[("shots", "fallback")]) is None  # local work has no price


def test_report_sections_and_numbers(log):
    text, events, n, bad = _report(log)
    assert f"from `runs.jsonl` ({n} lines, {len(events)} events, {bad} unreadable" in text
    assert "Generated 2026-11-26T12:00:00+00:00" in text
    for heading in ("## Headline", "## Per stage and model", "## What the cache saved", "## What a re-run costs",
                    "## Errors by kind", "## Prices used for the estimate", "## Data gaps in the log"):
        assert heading in text
    assert "Money actually spent: $0." in text
    # 3 cache hits vs 4 produced outputs (tts, keyframe, music, Ken Burns fallback)
    assert "3 jobs were served from the cache and 4 outputs were produced" in text
    assert "| kaggle | OutOfMemoryError | 1 |" in text
    assert "1 cache_hit event(s) could not be matched" in text
    assert "1 `fallback` event(s) in `narration`" in text  # the marker has no latency


def test_rerun_plan_is_rendered(log):
    plan = [costs.PlanRow("narration", 10, 0, 0, "provider API"),
            costs.PlanRow("keyframes", 9, 1, 0, "provider API"),
            costs.PlanRow("music", 0, 3, 0, "Kaggle/Colab notebook")]
    text, *_ = _report(log, plan=plan)
    assert "**1 provider call(s)**; 3 GPU job(s) still to make" in text
    assert "| keyframes | provider API | 9 | 1 | 0 |" in text


def test_cli_writes_costs_md_and_is_rerunnable(repo, capsys):
    repo.runs_log.write_text("\n".join(json.dumps(e) for e in EVENTS) + "\n", encoding="utf-8")
    assert main(["costs"], root=repo.root) == 0
    first = (repo.root / "COSTS.md").read_text(encoding="utf-8")
    assert "## What a re-run costs" in first and "| narration | provider API |" in first
    assert "| clips (Wan) | Kaggle/Colab notebook |" in first
    # the log grows; the report follows it
    with open(repo.runs_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(_event(stage="keyframes", status="cache_hit", input_hash="kkk")) + "\n")
    assert main(["costs"], root=repo.root) == 0
    second = (repo.root / "COSTS.md").read_text(encoding="utf-8")
    assert f"({len(EVENTS) + 1} lines" in second
    assert not (repo.root / "COSTS.md.tmp").exists()
