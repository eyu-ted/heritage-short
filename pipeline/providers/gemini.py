"""Thin wrapper over the Gemini API (google-genai SDK): text and text-to-speech.

TTS returns raw 16-bit PCM; we wrap it in a WAV header ourselves. The PCM is followed by a
signed C2PA content credential (Google's AI-provenance record), which is split off and
kept separately; see `split_c2pa` and FAILURES F11.
"""
from __future__ import annotations

import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TTS_RATE = 24000


@dataclass
class TextResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None


@dataclass
class AudioResult:
    pcm: bytes
    sample_rate: int
    mime_type: str
    input_tokens: int | None
    output_tokens: int | None
    provenance: bytes | None = None  # the C2PA manifest (JUMBF) that came with the audio

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / (2 * self.sample_rate)  # 16-bit mono


C2PA_CHUNK = b"C2PA"


def split_c2pa(data: bytes) -> tuple[bytes, bytes | None]:
    """Separate the speech from the content credential that follows it.

    Gemini TTS appends a signed C2PA manifest after the PCM as a RIFF-style chunk:
    b"C2PA" + uint32 little-endian size + a JUMBF box (b"jumb"). Written into a WAV as if it
    were samples, those ~7.7 KB play as 0.16 s of full-scale noise at the end of every line
    (+4 dBTP peaks; FAILURES F11). Only an exact match of that structure, ending exactly at
    the end of the data, is split off. Returns (pcm, manifest or None)."""
    idx = data.rfind(C2PA_CHUNK)
    while idx >= 0:
        size = int.from_bytes(data[idx + 4:idx + 8], "little")
        end = idx + 8 + size
        if len(data) in (end, end + 1) and data[idx + 12:idx + 16] == b"jumb" and idx % 2 == 0:
            return data[:idx], data[idx + 8:end]
        idx = data.rfind(C2PA_CHUNK, 0, idx)
    return data, None


def rate_from_mime(mime: str | None, default: int = DEFAULT_TTS_RATE) -> int:
    match = re.search(r"rate=(\d+)", mime or "")
    return int(match.group(1)) if match else default


def pcm_to_wav(pcm: bytes, sample_rate: int, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)


def _usage(resp: Any) -> tuple[int | None, int | None]:
    usage = getattr(resp, "usage_metadata", None)
    return (getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None))


# The SDK defaults to API v1, where TTS settings (speechConfig) do not exist and TTS
# models are not listed. Found in the Phase 2 smoke test (400 "Unknown name speechConfig").
API_VERSION = "v1beta"


class Gemini:
    def __init__(self, api_key: str, client: Any = None, api_version: str = API_VERSION):
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version=api_version))
        self.client = client

    def list_models(self) -> list[dict[str, Any]]:
        out = []
        for m in self.client.models.list():
            name = (getattr(m, "name", "") or "").removeprefix("models/")
            out.append({"name": name, "actions": list(getattr(m, "supported_actions", None) or [])})
        return out

    def generate_text(self, model: str, prompt: str, *, temperature: float = 0.4) -> TextResult:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            raise RuntimeError("Gemini returned no text (possibly blocked or empty)")
        return TextResult(text, *_usage(resp))

    def tts(self, model: str, text: str, *, voice: str, style: str | None = None) -> AudioResult:
        """The transcript goes in the text part; the style goes in speech_metadata.

        Smoke-test finding: putting the style in front of the text ("Speak slowly...: <line>")
        made one English line 13.6 s long instead of 4.8 s, i.e. the instruction was voiced.
        """
        from google.genai import types

        part = types.Part(
            text=text,
            speech_metadata=types.SpeechMetadata(style=style) if style else None,
        )
        resp = self.client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[part])],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )
        try:
            inline = resp.candidates[0].content.parts[0].inline_data
        except (AttributeError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini TTS returned no audio") from exc
        if not inline or not inline.data:
            raise RuntimeError("Gemini TTS returned empty audio")
        mime = inline.mime_type or ""
        pcm, provenance = split_c2pa(inline.data)
        return AudioResult(pcm, rate_from_mime(mime), mime, *_usage(resp), provenance=provenance)
