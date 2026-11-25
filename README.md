# Buna: a Heritage Short

A 60-90 second film about my grandmother's Ethiopian coffee ceremony, narrated in **Amharic** with **English subtitles** and an original score, made by a small pipeline in code. One file, [`storyboard.json`](storyboard.json), is the contract: every stage reads it and writes its outputs, and changing one line regenerates only what depends on it.

> **Status (25 Nov 2026): work in progress.** Done: engine, provider smoke test, Amharic narration, radio cut, reference sheet, all 10 keyframes, Ken Burns motion, vertical animatic. Next: Wan clips and music on Kaggle, final edit. See [IMPLEMENTATION.md](IMPLEMENTATION.md).

## How it works

```
storyboard.json  (validated by schema/storyboard.schema.json)
   ├─ narration   Gemini TTS, one Amharic WAV per shot           [done]
   ├─ keyframes   FLUX.2 klein-4b on Cloudflare Workers AI       [Phase 4]
   ├─ shots       Wan 2.2 on Kaggle, or a Ken Burns pan/zoom     [Phase 4/6]
   ├─ music       ACE-Step 1.5 on Kaggle                         [Phase 5]
   └─ assemble    FFmpeg: cut, duck, subtitles, loudness, end card, 9:16 + 16:9   [Phase 7]
```

- **Cache by hash:** every output file is named by a hash of its inputs (prompt, model, voice, upstream file hashes). Unchanged inputs are never regenerated. See [`pipeline/cache.py`](pipeline/cache.py).
- **Every model call is logged** to [`runs.jsonl`](runs.jsonl) (model, parameters, seed, latency, cost, attempt, errors); secrets are scrubbed.
- **Failures are classified** (transient / quota / daily quota / bad input / out of memory) and retried only when retrying can help. See [`pipeline/retry.py`](pipeline/retry.py).

## Setup

Requirements: Python 3.12, FFmpeg (a build with libass, e.g. `winget install Gyan.FFmpeg`).

```
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # then add your own keys; never commit .env
```

Keys needed (all free tiers): Google AI Studio (Gemini), Cloudflare Workers AI (account id + token with Workers AI permission), Kaggle (GPU notebooks).

The two GPU models (Wan 2.2 for motion, ACE-Step 1.5 for music) run in Kaggle notebooks, not from this machine. `export` writes a self-contained notebook (sources in [`notebooks/`](notebooks/)); you run it on Kaggle; `ingest` accepts only outputs whose job hash matches the current storyboard. See [`pipeline/kaggle.py`](pipeline/kaggle.py).
Instead of uploading by hand you can push the notebook with the Kaggle CLI (`pip install kaggle six`, `KAGGLE_API_TOKEN` and `KAGGLE_USERNAME` set): `kaggle kernels push -p kaggle/build/wan`, then `kaggle kernels output <user>/buna-wan -p kaggle/downloads/wan`. The notebook is created **private**.

## Commands

```
python -m pipeline validate             # check storyboard.json (schema + rules)
python -m pipeline all --dry-run        # show what is cached / would run / blocked; calls nothing
python -m pipeline narration            # generate missing narration lines only
python -m pipeline narration --shot s07 # one shot only
python -m pipeline radio                # radio cut: narration + placeholder music + subtitles on black
python -m pipeline refs                 # reference sheet options; then: refs --pick jebena=1
python -m pipeline keyframes            # stills; retake one by bumping keyframe.take in storyboard.json
python -m pipeline shots                # motion (Ken Burns locally; Wan clips are ingested from Kaggle)
python -m pipeline animatic             # vertical rough cut with pictures
python -m pipeline export wan --shot s07   # Kaggle notebook (jobs + keyframe inside) -> kaggle/build/
python -m pipeline export music            # Kaggle notebook for the 3 score candidates
python -m pipeline ingest wan --from <download>    # verify hashes, copy clips, log GPU minutes
python -m pipeline ingest music --from <download>
python -m pipeline radio --music score-seed22      # hear a score candidate under the narration
python -m pipeline music --pick score-seed22       # approve it (storyboard music.chosen)
python -m pipeline.contact keyframes    # contact sheet of all keyframes for review
python -m pipeline smoke                # call each provider once and record what really works
python -m pipeline all                  # the whole film (make film); finished stages come from cache
python -m pytest                        # tests (no network; the FFmpeg test renders a real radio cut)
```

Outputs are committed under `outputs/`, so a fresh clone can rebuild from cache with `--offline` and no API keys.

## The project documents

| File | What it holds |
|---|---|
| [PLAN.md](PLAN.md) | The design on paper, written before any code |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Step-by-step build plan and decision gates |
| [DESIGN.md](DESIGN.md) | Audience, intent, why each shot exists, user tests |
| [EXPERIMENTS.md](EXPERIMENTS.md) | Hypothesis → change → result, with run ids |
| [FAILURES.md](FAILURES.md) | What broke, what I tried, what fixed it |
| [ETHICS.md](ETHICS.md) | Consent record, licences, labelling, privacy |
| [script.md](script.md) | The approved Amharic / English narration script |

COSTS.md and ARCHITECTURE.md are written in Phase 9 from the logs.
