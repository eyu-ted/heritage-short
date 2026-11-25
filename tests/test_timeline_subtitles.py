from pipeline import subtitles, timeline


def _durations(sb, seconds):
    return {s["id"]: seconds for s in sb["shots"]}


def test_shots_follow_each_other_and_include_endcard(storyboard):
    slots, total = timeline.build(storyboard, _durations(storyboard, 3.0))
    for a, b in zip(slots, slots[1:]):
        assert b.start == a.end
    assert total == slots[-1].end + storyboard["endcard"]["duration_s"]


def test_long_narration_stretches_its_shot(storyboard):
    narr = _durations(storyboard, 3.0)
    narr["s07"] = 12.0
    slots, _ = timeline.build(storyboard, narr)
    s07 = next(s for s in slots if s.shot_id == "s07")
    assert s07.duration == 13.0  # 12 s line + 1 s breath beats the 8 s minimum


def test_narration_always_fits_inside_its_shot(storyboard):
    slots, _ = timeline.build(storyboard, _durations(storyboard, 9.5))
    for s in slots:
        assert s.narration_start + s.narration_s <= s.end


def test_chunks_respect_two_lines_of_forty():
    text = "Every morning, before the city woke, my grandmother my grandmother spread fresh grass on the floor."
    pieces = subtitles.chunk(text)
    assert len(pieces) == 2
    assert " ".join(pieces) == text
    assert pieces[0].endswith("woke,")  # breaks at the comma, no orphan like "the floor."
    for p in pieces:
        lines = subtitles.textwrap.wrap(p, subtitles.MAX_CHARS)
        assert len(lines) <= 2 and all(len(l) <= 40 for l in lines)


def test_lines_are_balanced():
    assert subtitles.lines_for("Short line.") == ("Short line.",)
    for text in ("One pot. Many cups. No one was ever left out.",
                 "By the third cup, strangers had become family."):
        lines = subtitles.lines_for(text)
        assert len(lines) == 2
        assert all(15 <= len(line) <= 40 for line in lines)  # no one-word orphan line


def test_cues_stay_inside_the_spoken_time(storyboard):
    slots, _ = timeline.build(storyboard, _durations(storyboard, 4.0))
    cues = subtitles.cues_for(slots)
    assert len(cues) >= len(slots)
    for slot in slots:
        mine = [c for c in cues if slot.narration_start <= c.start < slot.end]
        assert mine and abs(mine[-1].end - (slot.narration_start + 4.0)) < 0.01


def test_srt_format():
    srt = subtitles.to_srt([subtitles.Cue(1.5, 3.25, ("One pot.", "Many cups.")),
                            subtitles.Cue(3661.0, 3662.0, ("x",))])
    assert srt.startswith("1\n00:00:01,500 --> 00:00:03,250\nOne pot.\nMany cups.\n\n2\n01:01:01,000")
