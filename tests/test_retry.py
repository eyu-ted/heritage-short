import httpx
import pytest

from pipeline.retry import (
    BadInputError,
    OutOfMemoryError,
    QuotaError,
    TransientError,
    classify,
    with_retry,
)


def _http_error(status, headers=None):
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(status, request=request, headers=headers or {})
    return httpx.HTTPStatusError("boom", request=request, response=response)


class Flaky:
    """Fails with `errors` in order, then returns 'ok'."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    def __call__(self, attempt):
        self.calls.append(attempt)
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def test_transient_error_is_retried_then_succeeds():
    sleeps = []
    fn = Flaky(TransientError("blip"))
    assert with_retry(fn, sleep=sleeps.append) == "ok"
    assert fn.calls == [1, 2]
    assert len(sleeps) == 1


def test_gives_up_after_max_attempts():
    fn = Flaky(*[TransientError("down")] * 5)
    with pytest.raises(TransientError):
        with_retry(fn, attempts=3, sleep=lambda s: None)
    assert fn.calls == [1, 2, 3]


def test_bad_input_is_not_retried():
    fn = Flaky(_http_error(400))
    with pytest.raises(BadInputError):
        with_retry(fn, sleep=lambda s: None)
    assert fn.calls == [1]


def test_oom_is_not_retried():
    fn = Flaky(RuntimeError("CUDA out of memory"))
    with pytest.raises(OutOfMemoryError):
        with_retry(fn, sleep=lambda s: None)
    assert fn.calls == [1]


def test_quota_waits_at_least_retry_after():
    sleeps = []
    fn = Flaky(_http_error(429, {"retry-after": "30"}))
    assert with_retry(fn, sleep=sleeps.append, base_delay=1) == "ok"
    assert sleeps[0] >= 30


def test_on_error_sees_every_failure():
    seen = []
    fn = Flaky(TransientError("a"), TransientError("b"))
    with_retry(fn, sleep=lambda s: None, on_error=lambda n, e: seen.append((n, type(e).__name__)))
    assert seen == [(1, "TransientError"), (2, "TransientError")]


class SdkError(Exception):
    """Shape of google.genai.errors.APIError: an int `code` attribute."""

    def __init__(self, code, message):
        super().__init__(f"{code} {message}")
        self.code = code


@pytest.mark.parametrize(
    "exc, kind",
    [
        (SdkError(503, "UNAVAILABLE high demand"), TransientError),  # the real smoke-test case
        (SdkError(429, "RESOURCE_EXHAUSTED"), QuotaError),
        (SdkError(400, "INVALID_ARGUMENT"), BadInputError),
        (_http_error(429), QuotaError),
        (_http_error(503), TransientError),
        (_http_error(401), BadInputError),
        (httpx.ConnectTimeout("slow"), TransientError),
        (RuntimeError("RESOURCE_EXHAUSTED: quota"), QuotaError),
        (ValueError("bad"), BadInputError),
    ],
)
def test_classify(exc, kind):
    assert isinstance(classify(exc), kind)
