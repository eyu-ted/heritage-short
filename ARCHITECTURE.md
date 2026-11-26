# ARCHITECTURE: how the pipeline works

This describes the code as it is, not as it was planned (for the plan, see [PLAN.md](PLAN.md)). It is written for a reviewer who has not opened the code yet. Paths are relative to the repo root.

## 1. The idea in one paragraph

[`storyboard.json`](storyboard.json) (validated by [`schema/storyboard.schema.json`](schema/storyboard.schema.json) plus semantic checks in [`pipeline/storyboard.py`](pipeline/storyboard.py)) is the only input a human edits. Each stage turns it into a list of **jobs**. A job's output file is named by a **hash of everything that determines it**, so an unchanged job is never regenerated and a changed line regenerates only what depends on it. Every provider call, cache hit, fallback and local render is appended to [`runs.jsonl`](runs.jsonl). The two GPU models (Wan 2.2 and ACE-Step 1.5) cannot be called as an API on free hardware. They run in exported notebooks on Kaggle or Colab, and their outputs come back through a hash-checked `ingest`.

## 2. Data flow

```
                       storyboard.json  (schema + semantic checks)
                              |
     refs (pre-production) ---+--> approved reference images (storyboard references[].image)
                              |
   +--------------------------+-----------------------------+---------------------------+
   |                          |                             |                           |
narration                 keyframes                       music                         |
Gemini TTS                Cloudflare FLUX.2 klein-4b      job list only; generation     |
-> WAV + .c2pa sidecar    (+ ref image hashes)            runs in a notebook            |
   |  duration_s              |                             |                           |
   |                          +--> clips (Wan) ---export--> Kaggle/Colab notebook <-----+
   |                          |     job list only          (JOBS embedded; sidecar
   |                          |                              JSON per output with hash)
   |                          |                                   |
   |                          |                       ingest: hash == current job? 
   |                          |                       yes -> outputs/clips|music/
   |                          v                                   |
   +---- duration_s ----> shots (LOCAL, FFmpeg) <-----------------+ (Wan clip, if ingested)
   |                      Wan clip retimed, or Ken Burns
   |                      (Ken Burns = "fallback" for a wan shot)
   v                          v
 assemble (LOCAL, FFmpeg) <---+---- chosen score WAV, or the placeholder bed
 timeline -> audio master (compress, duck, measure, gain + 4x limiter, re-measure)
          -> picture (crop, crossfades, end card, burned ASS subtitles) -> AAC/H.264
          -> post-encode checks
 outputs/assemble/film_9x16__<hash>.mp4, film_16x9__<hash>.mp4, outputs/final/buna_en.srt

 Every box writes outputs/manifest.json (atomic) and appends to runs.jsonl.
```

## 3. Module map

| File | Role |
|---|---|
| [`pipeline/__main__.py`](pipeline/__main__.py) | CLI, stage driver (`_run_stage`), dry-run plan, exit codes |
| [`pipeline/config.py`](pipeline/config.py) | `STAGE_ORDER`, `Paths` (every location, so tests can redirect the whole tree), `.env` loading |
| [`pipeline/jobs.py`](pipeline/jobs.py), [`hashing.py`](pipeline/hashing.py), [`cache.py`](pipeline/cache.py) | `Job` and its hash, canonical JSON, the manifest |
| [`pipeline/runlog.py`](pipeline/runlog.py), [`calls.py`](pipeline/calls.py), [`retry.py`](pipeline/retry.py) | Run log, the one wrapper for every model call, error classification and retries |
| [`pipeline/providers/gemini.py`](pipeline/providers/gemini.py), [`cloudflare.py`](pipeline/providers/cloudflare.py) | Thin provider clients (TTS + C2PA split; FLUX image calls) |
| `narration.py`, `keyframes.py`, `shots.py`, `music.py`, `assemble.py` | The five stages: each exposes `jobs(sb, manifest)` and `run(ctx, todo)` |
| `refs.py`, `smoke.py`, `radio.py`, `kaggle.py`, `costs.py`, `contact.py` | Reference sheet, provider smoke test, radio cut / animatic, notebook export/ingest, COSTS.md, contact sheets |
| `timeline.py`, `subtitles.py`, `audio_split.py`, `ffmpeg.py` | Shared timeline, SRT/ASS cues, batch-narration splitter, FFmpeg/ffprobe wrappers |
| [`notebooks/wan_shots.py`](notebooks/wan_shots.py), [`ace_step_music.py`](notebooks/ace_step_music.py) | Notebook sources (percent format) that `export` turns into `.ipynb` |

## 4. Stages

`STAGE_ORDER = ("narration", "keyframes", "shots", "music", "assemble")` ([`pipeline/config.py`](pipeline/config.py)). `python -m pipeline all` runs them in that order. `_run_stage` in [`pipeline/__main__.py`](pipeline/__main__.py) does the same thing for every stage:

1. `jobs = module.jobs(sb, manifest)`, filtered by `--shot` for the shot-based stages.
2. Each job is **blocked** (an upstream output is missing, with the reason), **fresh** (logged as `cache_hit`), or **todo**.
3. Under `--offline`, any todo in a stage without `LOCAL = True` raises `NotReadyError`.
4. `module.run(ctx, todo)`. Then, if any job was blocked, the stage raises `NotReadyError` so the later stages do not run on partial inputs. Exception: in `all`, a music stage that is not ready is reported and skipped, and assembly uses the chosen score or the placeholder bed.

| Stage | Reads | Writes (`outputs/<stage>/<key>__<hash>.<ext>`) | Hash inputs (`Job.inputs`) |
|---|---|---|---|
| `refs` (pre-production, not in `all`) | references[] descriptions, style block | `refs/<ref>-opt<k>__h.jpg`; `--pick` writes the image path into storyboard | model, prompt, size, seed, option |
| `narration` | shots[].narration.am, narration_defaults | `narration/sNN__h.wav` + `.c2pa`; meta `duration_s` | model, language, text, voice, style |
| `keyframes` | keyframe prompt/seed/take, approved reference images | `keyframes/sNN__h.jpg` (1536 square) | model, composed prompt (shot + ref descriptions + style block), seed, size, take, **hash of each reference image file** |
| `clips` (made in a notebook) | keyframe file | `clips/sNN__h.mp4` via `ingest wan` | model, **keyframe file hash**, prompt + fixed style, negative prompt, seed, size, frames (121), steps, guidance, fps. **No duration.** |
| `shots` (`LOCAL`) | keyframe, narration duration, ingested clip | `shots/sNN__h.mp4` (1440 square master, 24 fps) | wan: backend, clip hash, keyframe hash, duration_s, fps, size, max_slowdown. kenburns: backend, keyframe hash, zoom, pan, duration_s, fps, size |
| `music` (made in a notebook) | music.cues[] | `music/<cue>-seed<n>__h.wav` via `ingest music`; `--pick` sets music.chosen | model, caption, bpm, keyscale, duration_s, instrumental, seed, ACE settings (variant, tag, steps, shift, thinking off) |
| `assemble` (`LOCAL`) | every narration + shot file, chosen score | `assemble/film_9x16__h.mp4`, `film_16x9__h.mp4`; `final/buna_en.srt` | `RECIPE` version, **file hash of every narration and shot**, score file hash or `placeholder:<expr>`, English lines, mix, end card, reframe, fps, crossfade, fade, mastering constants, encode settings, format, size |

`music.run` never generates anything: a todo music job always raises `NotReadyError` that points to `export music`. `smoke` and `refs` are commands outside `STAGE_ORDER`. Their calls are logged the same way.

## 5. The cache and hash contract

- **Hash:** `Job.hash = sha256(canonical_json({"stage", "key", **inputs}))[:12]` ([`pipeline/jobs.py`](pipeline/jobs.py)). Canonical JSON sorts keys and normalises numbers (`7 == 7.0`, floats rounded to 6 digits), so the hash only changes when the meaning changes ([`pipeline/hashing.py`](pipeline/hashing.py)).
- **Files:** `artifact_path` = `outputs/<stage>/<key>__<hash>.<ext>`. A new version gets a new name, so old takes are never overwritten and stay comparable.
- **Upstream files go in by content:** keyframes hash the approved reference images, shots and clips hash the keyframe file, and assemble hashes every narration and shot file. Re-picking a reference regenerates exactly the shots that use it. Retaking one keyframe invalidates one shot and both films, and nothing else (tested in [`tests/test_cli.py`](tests/test_cli.py)).
- **Deliberately left out:**
  - The Wan clip hash excludes the shot's length. Re-timing the narration re-renders the cheap local master (retime + scale) and never asks for GPU time again. This mattered in FAILURES F11, when every line got 0.16 s shorter and the queued Kaggle job stayed valid.
  - Narration hashes do not include batch versus single mode. A line is the same line however it was recorded. The uncut batch take has its own `batch__<hash>.wav`.
  - Measured results (loudness, durations) are outputs (manifest `meta`), never inputs. Run ids, timestamps and secrets are never in a hash.
  - Cloudflare seeds do not reproduce images (EXPERIMENTS E2), so a keyframe retake is an explicit `take` bump, not a seed change.
- **Manifest:** [`outputs/manifest.json`](outputs/manifest.json) stores `{stage: {key: {hash, path, status, produced_at, meta}}}`. A job is fresh only if the recorded hash equals the job hash **and** the file exists. Every `record` rewrites the manifest **atomically** (write `manifest.json.tmp`, then `os.replace`), so a crash never leaves half a manifest ([`pipeline/cache.py`](pipeline/cache.py)).
- **Stage-specific freshness:** a stage may define `is_fresh(ctx, job)`. `shots` uses it so that a Ken Burns stand-in is stale either when its own Ken Burns inputs change (it keeps `meta.fallback_hash`) or as soon as the real Wan clip is ingested.

## 6. runs.jsonl: the event schema

One JSON object per line, appended by `log_event` ([`pipeline/runlog.py`](pipeline/runlog.py)):

| Field | Meaning |
|---|---|
| `ts`, `run_id` | UTC timestamp (ms); one id per process (`HERITAGE_RUN_ID` or `<UTC time>-<6 hex>`) |
| `stage`, `shot_id` | stage name; shot id, candidate key, `film_9x16`, or a comma list for a batch request |
| `provider`, `model` | `gemini`, `cloudflare`, `kaggle`, `local` (FFmpeg); model id |
| `params`, `seed`, `input_hash`, `output` | the settings sent, seed, the job hash, the output path |
| `latency_ms`, `attempt` | wall time of this attempt; 1-based attempt number from the retry loop |
| `status` | one of `ok`, `error`, `cache_hit`, `fallback`, `skipped` (anything else is rejected) |
| `error`, `cost`, `gpu_minutes`, `note` | classified error text (truncated); usage units, e.g. `{"unit": "tokens", "input", "output", "audio_s"}`; notebook GPU time; free text |

Unknown field names raise. Before writing, any key that looks secret (`api_key`, `token`, `authorization`...) is blanked, and the real values of `GEMINI_API_KEY`, `CLOUDFLARE_API_TOKEN`, `KAGGLE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are replaced by `***` wherever they appear (the account id leaks into Cloudflare error URLs).

Who writes what: `logged_call` ([`pipeline/calls.py`](pipeline/calls.py)) logs **every attempt** of a provider call (`ok` with latency and cost, or `error` with the classified error). `_run_stage` logs one `cache_hit` per fresh job. Local renders log `provider: local`. `ingest` logs one event per sidecar, with `gpu_minutes` and the GPU name in `note`. `python -m pipeline costs` ([`pipeline/costs.py`](pipeline/costs.py)) rebuilds [COSTS.md](COSTS.md) from this file. Cache hits carry no provider, so the report attributes each one by `input_hash`.

**Failure handling** ([`pipeline/retry.py`](pipeline/retry.py)) sorts every exception into one of four kinds. `TransientError` (5xx, timeouts, including SDK errors that carry an int `code`) is retried with backoff. `QuotaError` (429) is retried more slowly, unless it is a daily limit or the server asks for a wait over 120 s; then it fails at once. `BadInputError` fails fast. `OutOfMemoryError` fails fast. Finished jobs are already cached, so re-running the same command continues where the last one stopped. Exit codes: 0 ok, 1 invalid storyboard or usage, 2 not ready, 3 provider failure, 4 FFmpeg failure.

## 7. Offline mode and `LOCAL` stages

`--offline` means "no provider calls", not "do nothing". `shots` and `assemble` declare `LOCAL = True` and still run (FFmpeg only), so a fresh clone with the committed `outputs/` rebuilds the films with `python -m pipeline all --offline` and no keys. A non-local stage with uncached jobs fails clearly with exit 2. The check lives in `_run_stage`, so the `refs` and `smoke` commands, which have their own code paths, do not check `--offline`.

## 8. Fallbacks and how the films record them

- **Ken Burns stand-ins.** A `wan` shot whose clip has not been ingested is rendered as a Ken Burns pan/zoom, if its storyboard `fallback` is `kenburns`. The file keeps the Wan job's hash with a `-kenburns` suffix, manifest `status: "fallback"`, and a `runs.jsonl` event with `status: fallback`. Without a fallback the stage stops with `NotReadyError`. When the clip arrives, `shots` retimes it to the slot (stretch at most 2x with `minterpolate` frame blending, then hold the last frame) and the stand-in goes stale.
- **Placeholder music bed.** While `music.chosen` is null, assembly mixes a quiet synthetic A/E drone (`radio.PAD_EXPR`), and the film's hash input is `placeholder:<expr>`. If a score is chosen but not ingested for the current cue settings, assembly is **blocked**. It does not fall back silently.
- **Batch narration.** All pending lines go out in one TTS request and are cut at the longest silences ([`pipeline/audio_split.py`](pipeline/audio_split.py)). If any piece's length is implausible for its line, a `fallback` event is logged and each line is requested on its own.
- **What the films record:** each film's manifest `meta` holds `music` (candidate key or `"placeholder"`), `shots` (per shot: `wan` or `kenburns`), the mastering measurements, and the post-encode check results. The `assemble` event in `runs.jsonl` repeats `music`, `wan_shots`, LUFS and true peak.

## 9. The notebook hand-off (Kaggle or Colab)

[`pipeline/kaggle.py`](pipeline/kaggle.py), targets `wan` (`shots.clip_jobs`) and `music` (`music.jobs`).

- **`export`** selects the jobs that are neither blocked nor fresh. It writes them **into** the notebook: the `JOBS = None` cell of the percent-format source is replaced by a literal list of `{key, hash, ext, **inputs}`. For Wan, the keyframe is embedded too, resized to the generation size, as `image_b64`. Output goes to `kaggle/build/<target>/`: the `.ipynb`, a readable `jobs.json` without images, and `kernel-metadata.json` (private, T4, internet on) for `kaggle kernels push`. Nothing else has to be uploaded.
- **The notebooks** check DNS first (fail in seconds without internet, FAILURES F10). Wan also runs a tiny preflight clip. Each job is then saved as soon as it is done, with a **sidecar JSON**: key, hash, status, file, GPU seconds, GPU name, settings, library versions, and an error and traceback on failure. A failed job does not stop the next one. On Colab the last cell zips `out/`.
- **`ingest --from <folder|zip>`** trusts nothing:
  - Zip members with absolute or `..` paths are refused.
  - Every sidecar is matched to the **current** job by key. A different hash is **stale** and skipped, because it was made from an older keyframe, prompt or setting.
  - A sidecar with `status != ok` is logged as an `error` event, with its GPU time and the notebook's error text, so notebook failures land in `runs.jsonl`.
  - Already-fresh outputs are skipped. A missing file is a failure. The media must pass `ffprobe`.
  - Accepted files are copied to `outputs/<stage>/<key>__<hash>.<ext>`, recorded in the manifest, and logged as `ok` with `gpu_minutes`.
  - The command exits 3 only if something failed and nothing was ingested.

## 10. Assembly and the audio master

[`pipeline/assemble.py`](pipeline/assemble.py), with the graph builders shared with the radio cut ([`pipeline/radio.py`](pipeline/radio.py)) so testers hear what the film does.

- **Timeline** ([`pipeline/timeline.py`](pipeline/timeline.py)): the narration sets the pace. Each shot lasts `max(min_duration_s, narration_s + narration_pad_s)`, and each line starts `narration_offset_s` into its slot. The film ends with the end card.
- **Audio, one master shared by both formats:**
  1. Each line is delayed to its slot and the lines are summed. The narration bus goes through the **voice compressor** (`acompressor` 2.5:1 above about -18 dBFS).
  2. **Ducking:** the score is levelled to a -26 LUFS bed with fades (or the placeholder pad: low-passed, slow tremolo, -10 dB). It is side-chain compressed by the narration, using the storyboard's `mix.duck`, then mixed with the voice into a float premix.
  3. **Measure** the premix (EBU R128 via `loudnorm` analysis). Gain = target LUFS minus measured LUFS.
  4. **Gain + 4x-oversampled limiter:** `volume` → `aresample=192000` → `alimiter` at `TP − 0.5 dB AAC headroom − 0.5 dB margin` → back to 48 kHz, 24-bit. Without oversampling, the limiter missed peaks between samples by 1.2 dB.
  5. **Re-measure.** If the master misses the target by more than 0.2 LU, the gain is corrected by the miss and step 4 runs again (at most 3 passes).
  6. **AAC** 192 kbps in the final encode.
- **Picture:** each square master is centre-cropped to 9:16 or 16:9. 0.5 s crossfades start exactly at the next slot's start, so picture never drifts against the narration. A 1 s fade to black leads into a black end-card segment. Subtitles and the end card ("Made with AI" + title) are burned in from one **ASS** file laid out in real pixels (at most 2 lines of 40 characters, no libass re-wrapping, FAILURES F9). The SRT is written to `outputs/final/buna_en.srt`.
- **Post-encode checks:** the delivered MP4 is measured again with ffprobe and loudnorm: duration within the brief's range, exact frame size, fps, LUFS within ±1 LU of target, and true peak ≤ the limit. Results go to the manifest and `runs.jsonl`. Misses are printed as `CHECK:` and stored in the event's `note`. They do not fail the stage.

## 11. C2PA provenance from Gemini TTS

Gemini returns the speech PCM followed by a signed **C2PA content credential**: `b"C2PA"` + uint32 size + a JUMBF box. `split_c2pa` in [`pipeline/providers/gemini.py`](pipeline/providers/gemini.py) splits it off only when that exact structure ends exactly at the end of the data. Before this fix, the credential was being played as 0.16 s of noise (FAILURES F11). The credential is **kept**: it is written next to each WAV as `<key>__<hash>.c2pa` (and next to the uncut batch take), and the manifest's `meta.c2pa` / `c2pa_bytes` point to it. The final films are re-encoded and cannot carry it, so the sidecars are the provider's provenance record. `python -m pipeline narration --repair-c2pa` fixed lines recorded before the fix without a new TTS request. Each repair is logged with the file hash before and after.

## 12. Tests

`python -m pytest -q` runs [`tests/`](tests/). There are no network calls: provider clients take injected fakes. The FFmpeg tests render real films at tiny sizes. Fixtures in [`tests/conftest.py`](tests/conftest.py) copy the schema and the **live** `storyboard.json` into `tmp_path` (`repo`, `refs_repo` with tiny reference images, `blank_repo` with empty Amharic), so tests never touch the real `outputs/` or `runs.jsonl`. Because the storyboard is copied as it is, tests follow its state. For example, a `music.chosen` that is not ingested in the temp repo blocks the assembly tests.

| File | Covers |
|---|---|
| `test_storyboard.py`, `test_hashing.py`, `test_cache.py` | schema and semantic validation; canonical hashing; manifest freshness and atomic save |
| `test_runlog.py`, `test_retry.py`, `test_providers.py` | event schema and redaction; error classification and backoff; Gemini/Cloudflare clients, model picking, secret scrubbing |
| `test_cli.py` | dry-run plan, exit codes, "change one prompt → only that shot reruns" |
| `test_audio_split.py`, `test_narration_radio.py`, `test_timeline_subtitles.py` | batch split; narration, offline refusal, radio cut; timeline and subtitle layout |
| `test_phase4.py`, `test_kaggle.py` | keyframes, Ken Burns, animatic; export/ingest (stale, failed, zipped, fallback replaced by an ingested clip) |
| `test_assemble.py` | both formats on target, rebuild scope, `all` past a missing score, C2PA split |
| `test_costs.py` | the COSTS.md generator on a synthetic log |
