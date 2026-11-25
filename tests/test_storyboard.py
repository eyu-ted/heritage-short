import copy

import pytest

from pipeline.storyboard import (
    StoryboardError,
    check_ready,
    load,
    planned_duration,
    shot_duration,
    validate,
)


def test_real_storyboard_is_valid(repo):
    sb = load(repo)
    assert 8 <= len(sb["shots"]) <= 12
    assert all(s["reason"] for s in sb["shots"])  # every shot has a stated reason


def test_planned_duration_in_range(storyboard):
    assert 60 <= planned_duration(storyboard) <= 90


def _errors(repo, sb):
    return validate(sb, repo)


def test_too_many_shots_rejected(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    extra = copy.deepcopy(sb["shots"][0])
    while len(sb["shots"]) < 13:
        extra = copy.deepcopy(extra)
        sb["shots"].append(extra)
    assert any("shots" in e for e in _errors(repo, sb))


def test_missing_reason_rejected(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    del sb["shots"][3]["reason"]
    assert any("reason" in e for e in _errors(repo, sb))


def test_duplicate_shot_id_rejected(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    sb["shots"][1]["id"] = sb["shots"][0]["id"]
    assert any("duplicate ids" in e for e in _errors(repo, sb))


def test_order_gap_rejected(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    sb["shots"][-1]["order"] = 99
    assert any("order" in e for e in _errors(repo, sb))


def test_unknown_backend_rejected(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    sb["shots"][0]["motion"]["backend"] = "sora"
    assert _errors(repo, sb)


def test_unknown_reference_rejected(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    sb["shots"][0]["keyframe"]["refs"] = ["dragon"]
    assert any("unknown reference" in e for e in _errors(repo, sb))


def test_chosen_music_must_exist(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    sb["music"]["chosen"] = "score-seed999"
    assert any("music/chosen" in e for e in _errors(repo, sb))


def test_duration_out_of_range_rejected(repo, storyboard):
    sb = copy.deepcopy(storyboard)
    for s in sb["shots"]:
        s["min_duration_s"] = 15  # 10 x 15 + 3 = 153 s
    assert any("planned duration" in e for e in _errors(repo, sb))


def test_load_raises_with_all_errors(repo, storyboard):
    import json

    sb = copy.deepcopy(storyboard)
    sb["shots"][0]["motion"]["backend"] = "sora"
    repo.storyboard.write_text(json.dumps(sb), encoding="utf-8")
    with pytest.raises(StoryboardError) as info:
        load(repo)
    assert info.value.errors


def test_narration_sets_shot_length(storyboard):
    shot = storyboard["shots"][0]  # min 7 s, pad 1 s
    assert shot_duration(storyboard, shot, None) == 7
    assert shot_duration(storyboard, shot, 4.0) == 7  # short line: minimum wins
    assert shot_duration(storyboard, shot, 8.2) == 9.2  # long line: line + breath


def test_check_ready_reports_missing_amharic(storyboard):
    sb = copy.deepcopy(storyboard)
    for s in sb["shots"]:
        s["narration"]["am"] = ""
    problems = check_ready(sb, "narration")
    assert problems and "Amharic" in problems[0]
    for s in sb["shots"]:
        s["narration"]["am"] = "ቡና"
    assert check_ready(sb, "narration") == []
