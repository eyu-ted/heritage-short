import math
import struct

import pytest

from pipeline import audio_split
from pipeline.retry import QuotaError, classify, with_retry

RATE = 8000  # low rate keeps the synthetic audio small and the tests fast


def tone(seconds, freq=220):
    return b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / RATE)))
                    for i in range(int(seconds * RATE)))


def silence(seconds):
    return b"\x00\x00" * int(seconds * RATE)


def speech_like(line_lengths, gap=1.2, breath=0.15):
    """Each 'line' is two bursts with a short breath inside; lines separated by long gaps."""
    out = silence(0.3)
    for n, length in enumerate(line_lengths):
        out += tone(length / 2) + silence(breath) + tone(length / 2)
        if n < len(line_lengths) - 1:
            out += silence(gap)
    return out + silence(0.4)


def test_finds_long_pauses_not_breaths():
    pcm = speech_like([2.0, 3.0, 2.5])
    silences = audio_split.find_silences(pcm, RATE)
    assert len([s for s in silences if s.length > 1.0]) == 2  # the two gaps between lines
    assert all(s.length >= audio_split.MIN_SILENCE_S for s in silences)  # 0.15 s breaths are ignored


def test_split_cuts_between_lines_and_trims():
    lengths = [2.0, 3.0, 2.5]
    texts = ["a" * 20, "b" * 30, "c" * 25]  # characters proportional to spoken length
    pieces = audio_split.split(speech_like(lengths), RATE, texts)
    assert len(pieces) == 3
    for piece, expected in zip(pieces, lengths):
        seconds = len(piece) / 2 / RATE
        assert expected <= seconds <= expected + 0.15 + 2 * audio_split.EDGE_PAD_S + 0.05


def test_split_refuses_when_pauses_are_missing():
    with pytest.raises(audio_split.SplitError, match="pauses"):
        audio_split.split(tone(5.0), RATE, ["a" * 10, "b" * 10])


def test_split_refuses_implausible_lengths():
    # Audio has lines of 1 s and 6 s, but the texts claim equal length: the cut is suspicious.
    with pytest.raises(audio_split.SplitError, match="ratio"):
        audio_split.split(speech_like([0.5, 6.0]), RATE, ["a" * 50, "b" * 2])


def test_single_line_is_returned_whole():
    pcm = tone(1.0)
    assert audio_split.split(pcm, RATE, ["x"]) == [pcm]


# ---- daily quota: fail fast instead of retrying (real 429 text, Phase 3) ----------

REAL_429 = ("429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generate_content_free_tier_requests, "
            "limit: 10, model: gemini-3.8-flash-tts ... 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' "
            "... {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '76072s'}")


class SdkError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def test_daily_quota_is_recognised():
    err = classify(SdkError(429, REAL_429))
    assert isinstance(err, QuotaError) and err.daily and err.retry_after == 76072


def test_daily_quota_is_not_retried():
    calls = []

    def fn(attempt):
        calls.append(attempt)
        raise SdkError(429, REAL_429)

    with pytest.raises(QuotaError):
        with_retry(fn, sleep=lambda s: pytest.fail("must not sleep for a daily limit"))
    assert calls == [1]


def test_per_minute_quota_is_still_retried():
    calls = []

    def fn(attempt):
        calls.append(attempt)
        if attempt == 1:
            raise SdkError(429, "429 RESOURCE_EXHAUSTED: requests per minute exceeded")
        return "ok"

    assert with_retry(fn, sleep=lambda s: None) == "ok"
    assert calls == [1, 2]
