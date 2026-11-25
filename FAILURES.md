# Failures journal

What broke, what I tried, what fixed it. Every entry points to evidence in `runs.jsonl` (by run id) or to a test.

---

## F1. Gemini TTS rejected every request (`400 Unknown name "speechConfig"`)
- **When:** Phase 2 smoke test, run `20261125T090707Z-94a69d`.
- **Symptom:** `gemini-3.1-flash-tts-preview` returned `400 INVALID_ARGUMENT: Unknown name "speechConfig" at 'generation_config'`. The model list for the key showed **no TTS models at all** (28 models).
- **Cause (two things):**
  1. The `google-genai` SDK (3.6.1) defaults to API **v1**. On v1, `speechConfig` does not exist and TTS models are not listed. They live on **v1beta** (65 models visible there).
  2. The model id had moved. The id I took from older search results (`gemini-3.1-flash-tts-preview`) is stale; current docs and the brief use **`gemini-3.8-flash-tts`**.
- **Fix:** client created with `api_version="v1beta"` (`pipeline/providers/gemini.py`), storyboard `models.tts` set to `gemini-3.8-flash-tts`. Next run `20261125T090833Z-feeb06`: Amharic and English TTS both `ok`.
- **Lesson:** a model list is only as true as the API version you asked. The brief warned that tools move; the smoke test caught it before any stage depended on it.

## F2. A temporary overload (503) was treated as "bad input" and never retried
- **When:** run `20261125T090707Z-94a69d`.
- **Symptom:** `gemini-3.8-flash` returned `503 UNAVAILABLE: high demand`, logged as `BadInputError`, with one attempt only.
- **Cause:** my own bug. `retry.classify()` only understood `httpx` errors; the Gemini SDK raises its own error type carrying the status as an int `code`, so it fell through to the default "bad input".
- **Fix:** `classify()` now reads an int `code` attribute (429 = quota, 5xx = transient, other 4xx = bad input). Test added (`tests/test_retry.py`, the 503 case). Next runs show 3 attempts with backoff.

## F3. The fallback model picker chose the wrong model, twice
- **When:** runs `94a69d` and `feeb06`.
- **Symptom 1:** fallback picked `gemini-omni-flash-preview` (a video model, which returned `429 RESOURCE_EXHAUSTED`, i.e. not on this free tier).
- **Cause 1:** sorting by version numbers put unversioned names first.
- **Symptom 2:** after the fix, it re-picked `gemini-3.8-flash`, the model that had just failed, so no fallback ran.
- **Fix:** versions are required, and the model that failed is excluded. Tests cover both real cases (`tests/test_providers.py`).

## F4. Gemini text models overloaded, then rate-limited (OPEN)
- **When:** runs `feeb06`, `2454ce`, `61b7c3` (~09:08-09:11 UTC, 25 Nov), `67c2c3` (09:59, worked once), `0bf4bd` (10:04).
- **Symptom:** `gemini-3.8-flash` and `gemini-3.7-flash` both `503 high demand` on all 3 attempts each; one attempt waited 33 s before failing. At 09:59 `gemini-3.8-flash` answered once (27 chars of Amharic). At 10:04 it was 503 again and `gemini-3.7-flash` returned `429 RESOURCE_EXHAUSTED`.
- **Impact:** the Amharic translation could not be relied on, so the first Amharic TTS samples used a short fixed sentence instead of a translated film line.
- **Workaround:** the narration script is short (10 lines) and the user is a native Amharic speaker, so the Amharic lines are written/reviewed by hand in S3.2, with Gemini as an optional draft when it is available. Translation is not on the critical path.

## F5. Cloudflare Workers AI: 401 / 403 (RESOLVED by the user)
- **When:** smoke runs `94a69d` to `61b7c3`.
- **Symptom:** image generation `401 Unauthorized`; model search `403 Forbidden`.
- **Diagnosis:** the token itself was valid and active: `accounts/<id>/tokens/verify` returned `200 active` (an account-owned token; the user-level verify endpoint correctly rejects it). So the token **lacked Workers AI permissions**.
- **Fix:** the user added Workers AI permissions to the token. Run `67c2c3`: model search `ok`, 5 FLUX models visible.

## F6. FLUX.1 schnell: `400 Additional properties '/seed' not allowed`
- **When:** run `67c2c3`.
- **Symptom:** every image request returned 400. My error message hid the reason; reading the response body showed `AiError: Bad input: Additional or unevaluated properties '/seed' at '/' not allowed`.
- **Cause:** on Cloudflare, schnell's input schema is only `{prompt, steps<=8}`: **no seed and no size**. FLUX.2 klein uses a different (multipart) format with `prompt, width, height, seed, input_image_0..3`.
- **Fix:** the Cloudflare provider now has a per-model capability table and refuses unsupported fields before calling; errors keep Cloudflare's explanation from the body; klein uses multipart. Run `0bf4bd`: schnell `ok` (1024x1024), klein-4b `ok` at the requested 1344x768. Tests in `tests/test_providers.py`.

## F7. Gemini free-tier rate limits hit during testing
- **When:** run `0bf4bd` (10:04 UTC).
- **Symptom:** `429 RESOURCE_EXHAUSTED` on `gemini-3.8-flash-tts` (after about 16 TTS requests across five smoke runs in ~1 hour) and on `gemini-3.7-flash`.
- **Impact and response:** the free TTS quota is the scarcest resource for narration (10 lines plus retakes). I stopped rerunning the smoke test, and the narration stage must cache every line and never re-request one that is already approved. Whether this is a per-minute or per-day limit is not known yet; the next narration run will tell. **Answered in F8.**

## F8. Daily TTS quota exhausted after the first narration line
- **When:** first real narration run, 25 Nov 10:51 UTC (`stage: narration` lines in `runs.jsonl`).
- **Symptom:** s01 generated (9.44 s), then `429 RESOURCE_EXHAUSTED ... GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 10, retryDelay: 76072s` (about 21 hours).
- **Cause:** the free tier allows **10 requests per model per day** for `gemini-3.8-flash-tts`. My own smoke tests had already used most of them (21 requests logged to that model today, 9 of them errors that also count). Lesson: provider checks spend the same quota as production; a smoke test should make one call per provider, not one per question.
- **Second problem it exposed (my bug):** the retry logic retried the daily 429 three times, which can never succeed in the same run.
- **What I tried / fixed:**
  1. `retry.py` now recognises daily limits (`PerDay` in the quota id, or a server retry delay > 120 s) and stops immediately with a clear message. Per-minute limits are still retried. Tests use the real 429 text.
  2. Each TTS model has its own quota, and the key also sees **`gemini-3.8-flash-lite-tts`**. Narration switched to it for the radio cut.
  3. Built **batch narration** (all lines in one request, cut at the pauses) to make 10 requests into 1. It was rejected by its own safety check (see EXPERIMENTS E4) and fell back to one request per line.
- **Result:** all 10 lines generated on the lite model (10:56-10:59 UTC). Three per-minute 429s on the lite model were waited out and retried successfully, which shows the daily/per-minute distinction working on real errors.
- **Open:** the user decides by ear whether the lite voice is good enough, or whether to regenerate with `gemini-3.8-flash-tts` after its quota resets (about 08:00 UTC, 26 Nov).

## F9. Vertical subtitles came out huge and re-wrapped into 3-4 lines
- **When:** first vertical animatic (`outputs/final/animatic_9x16.mp4`, 720x1280), Phase 4. Found by looking at extracted frames, not by the tests.
- **Symptom:** "One pot. Many cups. No one was ever left out." filled the middle of the frame in 3 lines, and the s01 line in 4, although the code produces at most 2 lines of 40 characters.
- **Cause:** burned-in SRT subtitles are laid out by libass on a fixed 288-pixel-high canvas and scaled to the video height. On a 1280-px-tall frame, `FontSize=18` became about 80 px, so libass re-wrapped the lines to fit 720 px.
- **Fix:** subtitles are now burned in from an **ASS** file laid out in real pixels for each format (`PlayResX/Y` = the video size), with `WrapStyle: 2` (no automatic re-wrapping) so the two-line breaks chosen in code are exactly what is shown. Font about 4.6% of the width (~40 characters across); bottom margin 20% of the height in vertical video, above the platform's buttons. The SRT is still written as the subtitle deliverable. Tests added (`tests/test_timeline_subtitles.py`).
- **Also fixed:** line breaks now prefer a punctuation boundary when the lines stay balanced, so the radio-cut review's "No / one" and "It was / her way" breaks are gone.
