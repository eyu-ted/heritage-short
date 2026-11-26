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

## F10. First Kaggle runs had no internet (phone verified; re-run queued, see F12)
- **When:** 25 Nov, about 12:27 UTC (15:27 EAT). Both notebooks were pushed with the Kaggle CLI (`buna-music` v1, `buna-wan` v1), on T4 x2 with `enable_internet: true`. Two `kaggle` lines with `status: error` are in `runs.jsonl`.
- **Symptom:** the music notebook failed at `git clone` (`Could not resolve host: github.com`, after 48 s). The Wan notebook spent 7 minutes on pip retries (`Failed to resolve 'pypi.org'`), then failed with `No matching distribution found for ftfy`. No model code ran.
- **Diagnosis:** the server-side metadata (`kaggle kernels pull -m`) confirms `enable_internet: true` and `machine_shape: NvidiaTeslaT4`, yet DNS failed for every host. This is how Kaggle behaves when the **account is not phone-verified**: internet is silently withheld.
- **Also learned from the log:** Kaggle's image now runs **Python 3.13**. ACE-Step 1.5 declares `>=3.11,<3.13`, which is why the notebook installs it with `--ignore-requires-python`. That combination is still untested.
- **Fixes in code:** both notebooks now check DNS in their first cell and stop within seconds with the fix spelled out, instead of retrying for minutes.
- **Needs the user:** phone verification on kaggle.com (Settings → Phone verification), then the same notebooks are pushed again.
- **Lesson:** a smoke test that only lists datasets with the API token (Phase 2) does not prove a notebook can reach the internet. The real check is a 10-second notebook that resolves a hostname.
- **Update:** the user phone-verified the account; both notebooks were pushed again as v2 at about 12:41 UTC (15:41 EAT). See F12.

## F11. Every narration line ended in 0.16 s of full-scale noise: Google's C2PA credential, played as audio
- **When:** found 25 Nov, about 18:00 UTC (21:00 EAT), in the first real assembly (Phase 7). It had been in every narration file since Phase 3.
- **Symptom:** the first master came out at **-15.0 LUFS** instead of -14. Its log line showed why: the mix peaked at **+4.3 dBTP** before any gain. Measuring each line: every one had a true peak of +3.0 to +4.3 dBTP and ~20 dB between peak and loudness (normal speech is ~12-15 dB).
- **Diagnosis, step by step:**
  1. The sample peak was 0 dBFS but only 2 samples reached it, with no flat clipping: a spike, not loud speech.
  2. The loudest samples of every line were all in its **last ~0.17 s**, and the sample values there were **byte-for-byte identical across different lines** (`-2712, -18115, 23433, 32758, ...`). Different recordings cannot share identical samples.
  3. Read as text, those bytes contain `cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia`, certificate validity dates and an ECDSA signature: a **C2PA content credential** (Google's signed "made by AI" provenance record).
  4. The layout is exact and the same in all 10 files: the speech PCM, then `b"C2PA"` + a 4-byte little-endian size (7656) + a JUMBF box (`jumb`, `jumd`, `c2pa`), 7664 bytes in total. That is 0.16 s when 24 kHz 16-bit audio is assumed.
- **Cause (my bug):** `providers/gemini.py` treated the whole `inline_data` of the TTS response as raw PCM and wrapped it in a WAV header, so the credential was written as samples and played as a burst of noise at the end of every line.
- **Fix:**
  1. `split_c2pa()` separates the credential from the speech, and only when that exact structure ends exactly at the end of the data. Tests use the real layout, plain audio, and the bytes "C2PA" appearing inside samples without the structure.
  2. The credential is **kept, not discarded**: it is written next to each WAV as `<line>__<hash>.c2pa`, and the manifest points to it. It is the provider's own AI-disclosure record, and our re-encoded audio cannot carry it.
  3. The 10 existing lines were repaired without spending TTS quota (`python -m pipeline narration --repair-c2pa`). Each repair is in `runs.jsonl` (model `repair-c2pa`) with the file hash before and after. Each line got 0.16 s shorter (s01: 8.33 s to 8.17 s).
- **Result:** narration true peaks dropped to between -0.8 and +1.0 dBTP, and loudness to -15.8 to -19.9 LUFS. Part of the loudness had been the noise.
- **Knock-on effects:**
  - Shot lengths follow the narration, so 7 Ken Burns shots re-rendered (about 1 minute, local). The Wan clip jobs did not change: the clip hash deliberately excludes duration, so the queued Kaggle job `s07 d57f16b275ed` is still valid.
  - The radio cut and animatic used in user test 1 still contain the noise. Testers may have heard a click at the end of each line. They are kept unchanged as the test record.
- **Open question (not verified):** the batch narration's cut was rejected by its own safety check (EXPERIMENTS E4). A burst of noise at the end of the batch take could have confused the silence detector. I have not re-tested this, so it stays a hypothesis.
- **Lesson:** "the bytes are raw PCM" was an assumption I never checked against the data. Provenance metadata is now common in generated media, and a loudness meter found it before anyone's ears did.

## F12. Kaggle v2 runs queued for 15+ hours without getting a GPU (OPEN)
- **When:** pushed 25 Nov about 12:41 UTC (15:41 EAT). Still `QUEUED` at 17:51 UTC (20:51 EAT), and still `QUEUED` the next morning, 26 Nov 03:58 UTC (06:58 EAT). `kernels list --mine` still shows the v1 run time (12:28 UTC), so neither notebook has started.
- **Checked:** the server-side metadata (`kernels pull -m`) is correct: T4 x2, internet on, private. The v1 runs this morning started within a minute with the same settings, so this is a Kaggle-side wait or an account limit, not the notebook.
- **Also learned:** the Kaggle CLI (2.2.5) has no cancel command. The only API way to stop a queued run is to delete the notebook.
- **Impact:** none on the film's existence. Assembly uses the Ken Burns stand-ins and the placeholder bed, and records which was used. The cache rebuilds only what changes when the clips and the score arrive.
- **Workaround (26 Nov morning):** the same exported notebooks were run by the user on Google Colab (free T4). The music notebook finished; its `out.zip` was ingested at about 08:30 EAT, with all 3 candidates passing their hash checks (GPU 11.3 s / 8.7 s / 8.8 s on a Tesla T4, per the sidecars). The notebooks needed no changes to run outside Kaggle, because `OUT` falls back to `./out` when `/kaggle/working` is missing. The Wan notebook's first Colab attempt stopped at the preflight cell with `NameError: name 'time' is not defined`. `time` is imported in cell 2, so the earlier cells' state was gone: the session had been restarted (most likely Colab's "restart session" prompt after the pip cell) and only the later cells were re-run. The fix is to run all cells again from the top. The second attempt then crashed with "Your session crashed after using all available RAM". The notebook was written for Kaggle's ~30 GB of RAM, but free Colab has ~12.7 GB, less than the 11 GB UMT5 text encoder (loaded on the CPU) plus the Python process, and less than the ~10 GB video model (CPU offload keeps it in RAM). Fix: when RAM is under 24 GB, both models load shard by shard **straight onto the GPU** (`device_map={"": 0}`) and the video model stays there without offload. The text encoder tries bf16 and then fp16 on the GPU, and every embedding is checked for NaN/inf. The Kaggle path is unchanged. On Colab the last cell also writes `out.zip`. In the third attempt the text encoding and the GPU loading both worked, but the preflight failed in fp16 and then in bf16 with `Expected all tensors to be on the same device, but got mat1 is on cpu`. The precomputed embeddings stay on the CPU. Under CPU offload, accelerate's hooks had been moving them to the GPU without my noticing; with the model loaded straight onto the GPU there are no hooks. Fix: `generate()` moves them to `cuda` itself. The preflight did its job: it caught this in 3 seconds instead of at the first real clip. After the one-line fix, "Run all" in the same session made the text encoder run out of GPU memory: the previous attempt's video model was still held in the kernel (11.97 GiB allocated). The workaround was to restart the session. The notebook now also frees any leftover `pipe` before encoding.
- **Fourth Colab attempt (`out (2).zip`, ingested so its errors are in `runs.jsonl`):** text encoding worked (GPU bf16, 273.5 s), and the preflight passed in fp16 (10.9 s at 256 px, 17 frames). Then all 3 real clips failed within ~1 s of starting with CUDA OOM: 13.98 GiB allocated of 14.56 GiB, failing on a 340 MiB allocation in the first transformer feed-forward. The weights alone nearly filled the T4: the fp16 transformer (~9.3 GiB) plus the fp32 VAE (~2.7 GiB). The preflight could not catch this, because at 256 px its activations are a fraction of the 640 px ones. **Lesson:** a preflight that is small enough to be fast does not prove the real size fits. Fix: on the low-RAM path the VAE waits on the CPU and is moved to the GPU only to encode the keyframe and to decode the result. The pipeline is pinned to run on `cuda`. `expandable_segments` reduces fragmentation.
- **Fifth Colab attempt:** the new memory plan worked through the whole denoising loop (preflight `2/2` steps). It then failed at the decode in fp16 and in bf16 with `Could not run 'aten::slow_conv3d_forward' with arguments from the 'CUDA' backend`. That message means a 3-D convolution got its input on the CPU and its weights on the GPU. Reading the diffusers source confirmed it: just before decoding, the pipeline does `latents.to(device=get_module_execution_device(self.vae))`, and at that moment the VAE was still on the CPU, so the latents were sent there. My wrapper moved the VAE to the GPU only inside `vae.decode`. Fix: the wrapper also moves its tensor arguments to the GPU. **Lesson:** moving a model behind a library's back breaks the library's own device bookkeeping. Each such move needs a check of what the library does just before and after the call. (The Kaggle runs are still queued.)
- **Sixth Colab attempt (`out (3).zip`):** the preflight passed, and for each of the 3 clips **all 30 denoising steps finished** (12:44 each, ~25 s/step on the T4). Each clip then failed in the VAE decode with CUDA OOM, about 20 min in: `unpatchify` was 568 MiB short, with 14.09 GiB allocated and a 15.24 GB peak. That 568 MiB is the whole decoded video at full size (121 × 3 × 640 × 640 fp32), so the tiled decode had finished every tile and failed only when putting them together, with the 9.3 GiB transformer still on the GPU. Fix: the clips are made in two phases. The pipeline's `vae.decode` is replaced by a stash that keeps the finished latents (the pipeline has already mixed in the keyframe and de-normalised them) and returns a dummy. The latents are saved to disk (~10 MB each). After all clips are denoised, the video model is deleted and a VAE alone on the GPU decodes them. The preflight runs the same denoise → stash → decode path at 256 px. Also fixed: a rerun used to skip any clip with a sidecar, **including error sidecars**, so "Run all again" would have retried nothing. Now only `status: ok` counts as done, and saved latents are reused. **Lesson:** the expensive work (denoising) succeeded three times and was thrown away because the cheap last step failed in the same process. Checkpoint the expensive part before the risky part.
