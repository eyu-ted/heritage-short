# ETHICS: consent, likeness, licences, labelling, privacy

## 1. Consent (the gate: recorded before anything of a real person is generated)

The film tells the story of a real person, the author's grandmother. She is **not named** in the film (see Privacy).

| Person | Role in the film | Consent needed for | Status |
|---|---|---|---|
| The author's grandmother | Her coffee ceremony is the story; represented by a stylised figure seen only from behind (`s08`) | Telling her story, a figure that represents her, public posting with an AI label | **GIVEN** (recorded 25 Nov 2026, before any narration or keyframe was generated) |
| The author (her grandchild) | Narrator's point of view (the voice is a preset TTS voice, not the author's) | n/a | n/a |

**Consent record**
- **Given by:** the grandmother herself.
- **Recorded:** 25 Nov 2026, as reported by the author: *"I have consent from my grandmother, she fully authorized it."*
- **Scope:** her story, a stylised figure representing her (no face, no photo), AI-generated narration in a preset voice, public posting with an AI label.
- **Recorded before generation:** this entry was written before the first narration line or keyframe of the film was generated (see the timestamps of the first `stage: narration` lines in `runs.jsonl`).

## 2. Likeness and voice
- **No real face or photo** is used anywhere. The elder in `s08` is a stylised, hand-painted figure seen only from behind, generated from a text description, not from any photograph of my grandmother or anyone else.
- **No voice cloning.** The narration uses a preset Gemini TTS voice (`Sulafat`). No real person's voice is recorded or imitated.
- Style is described by qualities (hand-painted, warm, film grain), not by naming any living artist.

## 3. Licences

| Component | Used for | Licence / terms | Output use |
|---|---|---|---|
| Gemini `gemini-3.8-flash-tts` / `gemini-3.8-flash-lite-tts` (Google AI Studio, free tier) | Narration | Gemini API Terms of Service | Generated audio may be used; free-tier inputs may be used by Google to improve products |
| FLUX.2 klein 4B on Cloudflare Workers AI | Keyframes | Model: Apache 2.0; service: Cloudflare terms | Usable; 4B chosen over 9B because 9B is non-commercial |
| FLUX.1 schnell on Cloudflare Workers AI | Fallback keyframes | Apache 2.0 | Usable |
| Wan 2.2 TI2V-5B (open weights, Kaggle) | Moving shots | Apache 2.0 | Usable |
| ACE-Step 1.5 (open weights, Kaggle) | Score | MIT; trained on licensed, royalty-free and synthetic data | Outputs usable commercially |
| FFmpeg (gyan.dev full build) | Assembly | GPL (tool only, not redistributed) | n/a |

To re-check on the day of release: Gemini and Cloudflare terms, since free tiers change.

## 4. Labelling
- The film ends with a visible end card: **"Made with AI"**.
- When posting, the platform's AI-content disclosure is switched on.
- Provenance metadata or watermarks added by any tool (e.g. SynthID) are left intact; the pipeline does not strip metadata.

## 5. Privacy
- Free endpoints may use inputs to improve their models. **Decision (author, 25 Nov 2026): the grandmother's name is not used in the film.** The narration and subtitles say "my grandmother" (አያቴ), so her name is never sent to any provider.
- No names, addresses, photos or other private details are sent to any provider.
