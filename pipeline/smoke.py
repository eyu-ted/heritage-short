"""python -m pipeline smoke  -  call every provider once and record what is REAL.

The brief warns that model names and free tiers move. This command answers,
with logged evidence, before we build on them:
  - which Gemini text / TTS model ids this key can actually use
  - does Amharic TTS work (you must listen to outputs/smoke/tts_am.wav)
  - which FLUX models Cloudflare offers on this account, and whether size is honoured
  - whether the Kaggle token authenticates

Every call is logged to runs.jsonl (stage "smoke"). Findings go to outputs/smoke/report.json.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any, Callable

import httpx
from PIL import Image

from .calls import logged_call
from .config import Paths, load_env, require_env
from .hashing import hash_file
from .keyframes import compose_prompt
from .providers.cloudflare import Cloudflare, estimate_neurons
from .providers.gemini import Gemini, pcm_to_wav
from .runlog import RUN_ID, log_event, Timer
from .storyboard import get_shot

STAGE = "smoke"
SAMPLE_SHOT = "s07"  # the hero line: "One pot. Many cups. No one is left out."
FALLBACK_AMHARIC = "ቡና ደርሷል። እንኳን ደህና መጣችሁ።"  # "The coffee is ready. Welcome."
TRANSLATE_PROMPT = (
    "Translate this line of documentary film narration into natural, warm, spoken Amharic, "
    "as an elder would say it during a coffee ceremony. Return only the Amharic text in Ge'ez "
    "script: no transliteration, no quotes, no explanation.\n\nLine: {line}"
)


_VERSIONED = re.compile(r"^gemini-(\d+(?:\.\d+)?)-")


def _version(name: str) -> float | None:
    """'gemini-3.8-flash' -> 3.8. Unversioned names (e.g. 'gemini-omni-flash-preview') -> None."""
    match = _VERSIONED.match(name)
    return float(match.group(1)) if match else None


def pick_text_model(names: list[str], exclude: tuple[str, ...] = ()) -> str | None:
    """Newest versioned plain Flash text model, skipping any model that just failed.
    (An earlier version picked the unversioned video model 'gemini-omni-flash-preview'
    because it sorted first, and later re-picked the model that had just failed.)"""
    skip = ("tts", "image", "embedding", "live", "audio", "lite", "thinking", "native", "vision", "preview")
    pool = [n for n in names if "flash" in n and n not in exclude
            and _version(n) is not None and not any(s in n for s in skip)]
    return max(pool, key=_version) if pool else None


def pick_tts_model(names: list[str]) -> str | None:
    pool = [n for n in names if "tts" in n and _version(n) is not None]
    flash = [n for n in pool if "flash" in n]
    return max(flash or pool, key=_version) if pool else None


class Smoke:
    def __init__(self, paths: Paths, sb: dict[str, Any]):
        self.paths, self.sb = paths, sb
        self.out = paths.outputs / "smoke"
        self.out.mkdir(parents=True, exist_ok=True)
        self.checks: list[dict[str, Any]] = []
        self.findings: dict[str, Any] = {}

    # -- bookkeeping ---------------------------------------------------------
    def check(self, name: str, fn: Callable[[], str]) -> bool:
        try:
            detail = fn()
            self.checks.append({"check": name, "ok": True, "detail": detail})
            return True
        except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not crash
            self.checks.append({"check": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:300]})
            return False

    def call(self, fn, **kw):
        return logged_call(self.paths, fn, stage=STAGE, attempts=3, **kw)

    # -- Gemini --------------------------------------------------------------
    def gemini(self) -> None:
        gem = Gemini(require_env("GEMINI_API_KEY"))
        names: list[str] = []
        shot = get_shot(self.sb, SAMPLE_SHOT)
        line_en = shot["narration"]["en"]

        def list_models() -> str:
            models = gem.list_models()
            names.extend(m["name"] for m in models)
            (self.out / "models_gemini.json").write_text(json.dumps(models, indent=2), encoding="utf-8")
            self.findings["gemini_text_candidates"] = [n for n in names if "flash" in n and "tts" not in n][:15]
            self.findings["gemini_tts_candidates"] = [n for n in names if "tts" in n]
            return f"{len(models)} models visible to this key"

        self.check("gemini: list models", list_models)

        amharic: dict[str, str] = {}

        def translate_with(model: str) -> str:
            res = self.call(
                lambda: gem.generate_text(model, TRANSLATE_PROMPT.format(line=line_en)),
                provider="gemini", model=model, shot_id=SAMPLE_SHOT,
                params={"task": "translate_en_am", "temperature": 0.4},
                cost=lambda r: {"unit": "tokens", "input": r.input_tokens, "output": r.output_tokens},
            )
            amharic["text"] = res.text
            (self.out / "translation_am.txt").write_text(res.text + "\n", encoding="utf-8")
            self.findings["text_model_working"] = model
            return f"{model}: {len(res.text)} chars of Amharic -> translation_am.txt"

        wanted = self.sb["models"]["text"]
        if not self.check(f"gemini text ({wanted})", lambda: translate_with(wanted)):
            alt = pick_text_model(names, exclude=(wanted,))
            if alt:
                self.check(f"gemini text fallback ({alt})", lambda: translate_with(alt))

        voice = self.sb["narration_defaults"]["voice"]
        style = self.sb["narration_defaults"]["style"]

        def speak_with(model: str, text: str, lang: str, use_style: bool = True) -> str:
            label = lang if use_style else f"{lang}_nostyle"
            this_style = style if use_style else None
            res = self.call(
                lambda: gem.tts(model, text, voice=voice, style=this_style),
                provider="gemini", model=model, shot_id=SAMPLE_SHOT,
                params={"task": f"tts_{label}", "voice": voice, "style": this_style},
                output=f"outputs/smoke/tts_{label}.wav",
                cost=lambda r: {"unit": "tokens", "input": r.input_tokens, "output": r.output_tokens,
                                "audio_s": round(r.duration_s, 2)},
            )
            pcm_to_wav(res.pcm, res.sample_rate, self.out / f"tts_{label}.wav")
            self.findings[f"tts_{label}"] = {"model": model, "seconds": round(res.duration_s, 2),
                                             "chars": len(text), "words": len(text.split()),
                                             "styled": use_style, "mime": res.mime_type}
            return f"{model}: {res.duration_s:.1f}s of audio -> tts_{label}.wav"

        am_text = amharic.get("text", FALLBACK_AMHARIC)
        tts_wanted = self.sb["models"]["tts"]
        tts_model = tts_wanted
        if not self.check(f"gemini TTS Amharic ({tts_wanted})", lambda: speak_with(tts_wanted, am_text, "am")):
            alt = pick_tts_model(names)
            if alt and alt != tts_wanted:
                tts_model = alt
                self.check(f"gemini TTS Amharic fallback ({alt})", lambda: speak_with(alt, am_text, "am"))
        self.check(f"gemini TTS English ({tts_model})", lambda: speak_with(tts_model, line_en, "en"))
        # Is the style instruction being spoken aloud? Same line, no style: compare durations.
        self.check(f"gemini TTS English, no style ({tts_model})",
                   lambda: speak_with(tts_model, line_en, "en", use_style=False))

    # -- Cloudflare ----------------------------------------------------------
    def cloudflare(self) -> None:
        cf = Cloudflare(require_env("CLOUDFLARE_ACCOUNT_ID"), require_env("CLOUDFLARE_API_TOKEN"))
        found: list[str] = []

        def search() -> str:
            models = cf.search_models("flux")
            found.extend(m["name"] for m in models if m.get("name"))
            (self.out / "models_cloudflare.json").write_text(json.dumps(models, indent=2), encoding="utf-8")
            self.findings["cloudflare_flux_models"] = found
            return f"{len(found)} FLUX models: {', '.join(found)}"

        self.check("cloudflare: search FLUX models", search)

        shot = get_shot(self.sb, SAMPLE_SHOT)
        prompt = compose_prompt(self.sb, shot)
        seed, steps = shot["keyframe"]["seed"], self.sb["render"]["image_steps"]
        want_w, want_h = self.sb["render"]["keyframe_size"]

        digests: dict[str, str] = {}

        def generate(model: str, label: str, **kw: Any) -> str:
            data = self.call(
                lambda: cf.image(model, prompt, **kw),
                provider="cloudflare", model=model, shot_id=SAMPLE_SHOT, seed=kw.get("seed"),
                params={k: v for k, v in kw.items() if k != "seed"},
                cost=lambda _: {"unit": "neurons",
                                "amount": estimate_neurons(model, 1024, 1024, kw.get("steps") or 4),
                                "estimated": True},
            )
            img = Image.open(io.BytesIO(data))
            ext = (img.format or "png").lower().replace("jpeg", "jpg")
            path = self.out / f"image_{label}.{ext}"
            path.write_bytes(data)
            digests[label] = hash_file(path)
            self.findings[f"image_{label}"] = {"model": model, "requested": kw,
                                               "returned": list(img.size), "format": img.format,
                                               "bytes": len(data), "sha": digests[label]}
            return f"{model}: got {img.size[0]}x{img.size[1]} {img.format} -> {path.name}"

        schnell = "@cf/black-forest-labs/flux-1-schnell"
        klein = "@cf/black-forest-labs/flux-2-klein-4b"  # Apache 2.0; the 9B is non-commercial
        self.check("cloudflare image: schnell (prompt + steps only)",
                   lambda: generate(schnell, "schnell", steps=steps))
        if klein in found:
            sized = dict(seed=seed, width=want_w, height=want_h)
            self.check(f"cloudflare image: klein-4b, seed {seed}, {want_w}x{want_h}",
                       lambda: generate(klein, "klein4b_a", **sized))
            self.check("cloudflare image: klein-4b, same seed again",
                       lambda: generate(klein, "klein4b_b", **sized))

            def same_seed_same_image() -> str:
                if {"klein4b_a", "klein4b_b"} - set(digests):
                    raise RuntimeError("both klein images are needed for this check")
                identical = digests["klein4b_a"] == digests["klein4b_b"]
                self.findings["klein4b_seed_reproducible"] = identical
                return "identical bytes" if identical else "DIFFERENT bytes: seed does not pin the image"

            self.check("cloudflare: same seed -> same image?", same_seed_same_image)

    # -- Kaggle --------------------------------------------------------------
    def kaggle(self) -> None:
        def auth() -> str:
            token = require_env("KAGGLE_API_TOKEN")
            timer = Timer()
            with timer:
                r = httpx.get("https://www.kaggle.com/api/v1/datasets/list",
                              params={"search": "wan2.2", "page": 1},
                              headers={"Authorization": f"Bearer {token}"}, timeout=30)
            status = "ok" if r.status_code == 200 else "error"
            log_event(self.paths.runs_log, stage=STAGE, provider="kaggle", model="kaggle-api",
                      params={"endpoint": "datasets/list"}, status=status, attempt=1,
                      latency_ms=timer.ms, error=None if status == "ok" else f"HTTP {r.status_code}")
            r.raise_for_status()
            return f"token accepted (HTTP {r.status_code}, {timer.ms} ms)"

        self.check("kaggle: API token", auth)

    # -- report --------------------------------------------------------------
    def report(self) -> bool:
        path = self.out / "report.json"
        path.write_text(json.dumps({"run_id": RUN_ID, "checks": self.checks, "findings": self.findings},
                                   indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSMOKE TEST  (run {RUN_ID})")
        print("-" * 78)
        for c in self.checks:
            print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['check']}")
            print(f"       {c['detail'].encode('ascii', 'replace').decode()}")
        print("-" * 78)
        print(f"details: {self.paths.rel(path)}   log: runs.jsonl")
        essential = ("gemini text", "gemini TTS Amharic", "cloudflare image: klein-4b, seed")
        return all(any(c["ok"] for c in self.checks if c["check"].startswith(e)) for e in essential)


def run(paths: Paths, sb: dict[str, Any]) -> int:
    load_env(paths)
    smoke = Smoke(paths, sb)
    smoke.check("gemini (setup)", lambda: (smoke.gemini(), "done")[1])
    smoke.check("cloudflare (setup)", lambda: (smoke.cloudflare(), "done")[1])
    smoke.kaggle()
    return 0 if smoke.report() else 1
