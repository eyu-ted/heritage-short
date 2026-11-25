"""Provider wrappers and the logged-call helper, tested without any network access."""
import base64
import io
import json
import wave
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from pipeline.calls import logged_call
from pipeline.providers.cloudflare import Cloudflare, estimate_neurons
from pipeline.providers.gemini import Gemini, pcm_to_wav, rate_from_mime
from pipeline.retry import BadInputError
from pipeline.runlog import log_event
from pipeline.smoke import pick_text_model, pick_tts_model


def _png_bytes(size=(16, 9)):
    buf = io.BytesIO()
    Image.new("RGB", size, "brown").save(buf, format="PNG")
    return buf.getvalue()


def _lines(paths):
    return [json.loads(l) for l in paths.runs_log.read_text(encoding="utf-8").splitlines()]


# ---- logged_call -----------------------------------------------------------

def test_logged_call_logs_success_with_cost(repo):
    out = logged_call(repo, lambda: "img", stage="keyframes", provider="cloudflare", model="flux",
                      shot_id="s07", seed=1007, cost=lambda r: {"unit": "neurons", "amount": 57.6})
    assert out == "img"
    (line,) = _lines(repo)
    assert line["status"] == "ok" and line["attempt"] == 1 and line["shot_id"] == "s07"
    assert line["cost"]["amount"] == 57.6 and line["latency_ms"] >= 0


def test_logged_call_logs_each_failed_attempt(repo):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise httpx.ConnectError("network down")
        return "ok"

    assert logged_call(repo, flaky, stage="x", provider="p", model="m", sleep=lambda s: None) == "ok"
    statuses = [(l["status"], l["attempt"]) for l in _lines(repo)]
    assert statuses == [("error", 1), ("ok", 2)]


def test_logged_call_does_not_retry_bad_input(repo):
    def bad():
        raise ValueError("nonsense prompt")

    with pytest.raises(BadInputError):
        logged_call(repo, bad, stage="x", provider="p", model="m", sleep=lambda s: None)
    assert len(_lines(repo)) == 1


def test_real_secret_values_never_reach_the_log(repo, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SUPERSECRETKEY123")
    log_event(repo.runs_log, stage="x", status="error", error="failed for key SUPERSECRETKEY123")
    text = repo.runs_log.read_text(encoding="utf-8")
    assert "SUPERSECRETKEY123" not in text and "***" in text


def test_cloudflare_account_id_in_error_urls_is_redacted(repo, monkeypatch):
    # Real case from the pre-push scan: Cloudflare error URLs contain the account id.
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "0123456789abcdef0123456789abcdef")
    log_event(repo.runs_log, stage="x", status="error",
              error="401 for url 'https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/ai/run/m'")
    assert "0123456789abcdef0123456789abcdef" not in repo.runs_log.read_text(encoding="utf-8")


# ---- Cloudflare ------------------------------------------------------------

def _cf(handler):
    return Cloudflare("acct", "tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


SCHNELL = "@cf/black-forest-labs/flux-1-schnell"
KLEIN = "@cf/black-forest-labs/flux-2-klein-4b"


def _ok_image():
    return httpx.Response(200, json={"success": True,
                                     "result": {"image": base64.b64encode(_png_bytes()).decode()}})


def test_schnell_sends_json_with_only_prompt_and_steps():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return _ok_image()

    data = _cf(handler).image(SCHNELL, "a jebena", steps=4)
    assert Image.open(io.BytesIO(data)).size == (16, 9)
    assert seen["url"].endswith(f"/accounts/acct/ai/run/{SCHNELL}")
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"prompt": "a jebena", "steps": 4}


def test_schnell_rejects_seed_and_size_before_calling():
    # Real smoke-test finding: Cloudflare answers 400 "Additional properties '/seed' not allowed".
    cf = _cf(lambda r: pytest.fail("must not reach the network"))
    with pytest.raises(ValueError, match="seed"):
        cf.image(SCHNELL, "p", seed=7)
    with pytest.raises(ValueError, match="size"):
        cf.image(SCHNELL, "p", width=1344, height=768)


def test_klein_sends_multipart_with_seed_size_and_refs():
    seen = {}

    def handler(request):
        seen["ctype"] = request.headers["content-type"]
        seen["body"] = request.content
        return _ok_image()

    _cf(handler).image(KLEIN, "a jebena", seed=1007, width=1344, height=768, refs=[_png_bytes()])
    body = seen["body"]
    assert seen["ctype"].startswith("multipart/form-data")
    for field in (b'name="prompt"', b'name="seed"', b"1007", b'name="width"', b"1344", b'name="input_image_0"'):
        assert field in body
    assert b'name="steps"' not in body  # klein's steps are fixed at 4


def test_klein_rejects_steps_and_too_many_refs():
    cf = _cf(lambda r: pytest.fail("must not reach the network"))
    with pytest.raises(ValueError, match="steps"):
        cf.image(KLEIN, "p", steps=8)
    with pytest.raises(ValueError, match="at most 4"):
        cf.image(KLEIN, "p", refs=[b"x"] * 5)


def test_unknown_model_rejected():
    with pytest.raises(ValueError, match="Unknown image model"):
        _cf(lambda r: _ok_image()).image("@cf/someone/else", "p")


def test_raw_image_response():
    png = _png_bytes()
    data = _cf(lambda r: httpx.Response(200, content=png, headers={"content-type": "image/png"})).image(SCHNELL, "p")
    assert data == png


def test_http_error_keeps_cloudflare_explanation():
    with pytest.raises(httpx.HTTPStatusError, match="Bad input: seed not allowed"):
        _cf(lambda r: httpx.Response(400, json={"errors": [{"message": "Bad input: seed not allowed"}]})).image(SCHNELL, "p")


def test_neuron_estimate_for_schnell():
    # 1024x1024 = 4 tiles * 4.8 + 4 steps * 9.6 = 57.6
    assert estimate_neurons("@cf/black-forest-labs/flux-1-schnell", 1024, 1024, 4) == 57.6
    assert estimate_neurons("unknown-model", 1024, 1024, 4) is None


# ---- Gemini ----------------------------------------------------------------

class FakeModels:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return self.response

    def list(self):
        return [SimpleNamespace(name="models/gemini-x-flash", supported_actions=["generateContent"])]


def test_gemini_tts_returns_pcm_and_rate():
    pcm = b"\x00\x01" * 24000  # 1 second at 24 kHz
    part = SimpleNamespace(inline_data=SimpleNamespace(data=pcm, mime_type="audio/L16;codec=pcm;rate=24000"))
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
                           usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=25))
    fake = FakeModels(resp)
    gem = Gemini("k", client=SimpleNamespace(models=fake))
    audio = gem.tts("tts-model", "ቡና", voice="Sulafat", style="Speak warmly.")
    assert audio.sample_rate == 24000 and audio.duration_s == pytest.approx(1.0)
    part = fake.kwargs["contents"][0].parts[0]
    assert part.text == "ቡና"  # transcript only: the style must not be spoken
    assert part.speech_metadata.style == "Speak warmly."


def test_gemini_tts_without_style_has_no_metadata():
    part_out = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x00\x00", mime_type="audio/L16;rate=24000"))
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part_out]))],
                           usage_metadata=None)
    fake = FakeModels(resp)
    Gemini("k", client=SimpleNamespace(models=fake)).tts("m", "line", voice="v")
    assert fake.kwargs["contents"][0].parts[0].speech_metadata is None


def test_gemini_tts_without_audio_raises():
    resp = SimpleNamespace(candidates=[], usage_metadata=None)
    gem = Gemini("k", client=SimpleNamespace(models=FakeModels(resp)))
    with pytest.raises(RuntimeError):
        gem.tts("m", "text", voice="v")


def test_gemini_list_models_strips_prefix():
    gem = Gemini("k", client=SimpleNamespace(models=FakeModels(None)))
    assert gem.list_models()[0]["name"] == "gemini-x-flash"


def test_pcm_to_wav_roundtrip(tmp_path):
    path = tmp_path / "a.wav"
    pcm_to_wav(b"\x00\x00" * 2400, 24000, path)
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (24000, 1, 2400)


def test_helpers():
    assert rate_from_mime("audio/L16;codec=pcm;rate=16000") == 16000
    assert rate_from_mime(None) == 24000


def test_model_pickers_prefer_newest():
    names = ["gemini-2.5-flash", "gemini-3.1-flash", "gemini-3.8-flash-lite", "gemini-3.1-flash-tts-preview",
             "gemini-3.8-flash-tts", "gemini-embedding-001"]
    assert pick_text_model(names) == "gemini-3.1-flash"
    assert pick_tts_model(names) == "gemini-3.8-flash-tts"
    assert pick_text_model([]) is None


def test_text_picker_skips_unversioned_models():
    # Real list seen in the smoke test: the unversioned video model must not be chosen.
    names = ["gemini-omni-flash-preview", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert pick_text_model(names) == "gemini-3.8-flash"
    # ...and never re-picks the model that just failed (real smoke-test case: 503 on 3.8).
    assert pick_text_model(names, exclude=("gemini-3.8-flash",)) == "gemini-3.7-flash"
