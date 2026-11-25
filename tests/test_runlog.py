import json

import pytest

from pipeline.runlog import FIELDS, RUN_ID, Timer, log_event


def test_writes_one_valid_json_line_per_call(tmp_path):
    log = tmp_path / "runs.jsonl"
    log_event(log, stage="keyframes", shot_id="s07", provider="cloudflare", model="flux",
              seed=1007, latency_ms=2140, status="ok", attempt=1)
    log_event(log, stage="keyframes", shot_id="s08", status="cache_hit")
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["run_id"] == RUN_ID
    assert first["seed"] == 1007 and first["status"] == "ok"
    assert set(FIELDS) <= set(first)  # every field present, even if null


def test_secrets_are_redacted(tmp_path):
    log = tmp_path / "runs.jsonl"
    rec = log_event(log, stage="x", status="ok",
                    params={"api_key": "SECRET", "headers": {"Authorization": "Bearer X"}, "steps": 4})
    assert rec["params"]["api_key"] == "***"
    assert rec["params"]["headers"]["Authorization"] == "***"
    assert rec["params"]["steps"] == 4
    assert "SECRET" not in log.read_text(encoding="utf-8")


def test_unknown_field_rejected(tmp_path):
    with pytest.raises(ValueError):
        log_event(tmp_path / "r.jsonl", stage="x", status="ok", colour="red")


def test_bad_status_rejected(tmp_path):
    with pytest.raises(ValueError):
        log_event(tmp_path / "r.jsonl", stage="x", status="done")


def test_timer_measures_milliseconds():
    with Timer() as t:
        sum(range(1000))
    assert isinstance(t.ms, int) and t.ms >= 0
