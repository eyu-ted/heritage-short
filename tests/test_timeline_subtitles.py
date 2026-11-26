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
    text = "Every morning, before the city woke, my grandmother always spread fresh grass on the floor."
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


def test_breaks_prefer_punctuation_over_splitting_a_phrase():
    # Both cases were flagged in the radio-cut review ("No / one", "It was / her way").
    assert subtitles.lines_for("One pot. Many cups. No one was ever left out.") == (
        "One pot. Many cups.", "No one was ever left out.")
    assert subtitles.lines_for("Incense filled the room. It was her way of saying: welcome.") == (
        "Incense filled the room.", "It was her way of saying: welcome.")


def test_ass_is_laid_out_in_real_pixels_without_rewrapping():
    cues = [subtitles.Cue(1.5, 3.25, ("One pot. Many cups.", "No one was ever left out."))]
    vertical = subtitles.to_ass(cues, 720, 1280)
    assert "PlayResX: 720" in vertical and "PlayResY: 1280" in vertical
    assert "WrapStyle: 2" in vertical
    assert "Dialogue: 0,0:00:01.50,0:00:03.25,Default,,0,0,0,,One pot. Many cups.\\NNo one was ever left out." in vertical
    v, h = subtitles.style_for(720, 1280), subtitles.style_for(1280, 720)
    assert 28 <= v["font"] <= 40 and v["margin_v"] >= 0.19 * 1280  # above the phone feed's buttons
    assert h["margin_v"] < v["margin_v"]


def test_user_test_2_subtitle_look_bigger_boxed_and_still_fits():
    """User test 2: text too small, no background, too low. The 9:16 look is bigger, boxed,
    higher, and its lines are shorter so the bigger text still fits across the frame."""
    look = subtitles.look_for({"scale": 1.2, "box": True, "vertical_max_chars": 32,
                               "vertical_margin": 0.22}, 1080, 1920)
    assert look["max_chars"] == 32 and look["box"]
    assert subtitles.look_for({"vertical_max_chars": 32}, 1920, 1080)["max_chars"] == subtitles.MAX_CHARS
    text = "Every morning, before the city woke, my grandmother spread fresh grass on the floor."
    for piece in subtitles.chunk(text, 32):
        assert all(len(line) <= 32 for line in subtitles.lines_for(piece, 32))
    ass = subtitles.to_ass([subtitles.Cue(0, 1, ("Hello",))], 1080, 1920, scale=1.2, box=True,
                           vertical_margin=0.22)
    default = subtitles.style_for(1080, 1920)
    big = subtitles.style_for(1080, 1920, 1.2, 0.22)
    assert big["font"] > default["font"] and big["margin_v"] > default["margin_v"]
    style = next(line for line in ass.splitlines() if line.startswith("Style: Default"))
    assert ",&H60000000," in style and style.split(",")[15] == "3"  # BorderStyle 3: opaque box
    # Default (radio cut, SRT): unchanged look
    plain = subtitles.to_ass([subtitles.Cue(0, 1, ("Hello",))], 1080, 1920)
    assert next(l for l in plain.splitlines() if l.startswith("Style: Default")).split(",")[15] == "1"


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
