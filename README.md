# Buna: a Heritage Short

A 60-90 second film about my grandmother's Ethiopian coffee ceremony, narrated in **Amharic** with **English subtitles** and an original score, made by a small pipeline in code. One file, [`storyboard.json`](storyboard.json), is the contract: every stage reads it and writes its outputs, and changing one line regenerates only what depends on it.

> **Status (26 Nov 2026): complete.** The **final edit is done in both formats: 81.5 s, -14.2 LUFS, -1.9 dBTP.**
> - Narration: Amharic, made with Gemini TTS.
> - Pictures: 10 keyframes. Three hero shots (s03, s07, s10) have real motion from **Wan 2.2**, made on a free Colab T4 after Kaggle never gave the runs a GPU ([FAILURES F12](FAILURES.md)). The other seven use a Ken Burns pan/zoom.
> - Music: an original score from ACE-Step 1.5 (`score-seed22`, [EXPERIMENTS E8](EXPERIMENTS.md)).
> - Two user tests with three people each ([DESIGN §4-5](DESIGN.md)). Their feedback changed the storyboard: subtitles, ducking, end card, pacing and spelling.
>
> Still open: the voice sounds "like reading" to all three listeners ([FAILURES F13](FAILURES.md)).

**Watch the film:** [9:16 (vertical)](https://www.youtube.com/shorts/SjnmskgFBjo) · [16:9 (horizontal)](https://youtu.be/rD2WWXy8G6Q) · [Walkthrough (how it was built, one shot regenerated live)](https://drive.google.com/file/d/1EjD9-vuzIhLtWg7eoS284Ycmp5YzrJux/view?usp=sharing)

The code was written with an AI coding assistant (Claude Code) under my direction.

## How it works

```
storyboard.json  (validated by schema/storyboard.schema.json)
   ├─ narration   Gemini TTS, one Amharic WAV per shot           [done]
   ├─ keyframes   FLUX.2 klein-4b on Cloudflare Workers AI       [done]
   ├─ shots       Wan 2.2 on Kaggle/Colab, or a Ken Burns pan/zoom [done: Wan s03/s07/s10, Ken Burns 7]
   ├─ music       ACE-Step 1.5 on Kaggle/Colab                   [done: score-seed22]
   └─ assemble    FFmpeg: crossfades, duck, subtitles, measured mastering, end card, 9:16 + 16:9   [done]
```

- **Cache by hash:** every output file is named by a hash of its inputs (prompt, model, voice, upstream file hashes). Unchanged inputs are never regenerated. See [`pipeline/cache.py`](pipeline/cache.py).
- **Every model call is logged** to [`runs.jsonl`](runs.jsonl) (model, parameters, seed, latency, cost, attempt, errors); secrets are scrubbed.
- **What it costs:** $0 spent. Every provider was used on its free tier (Gemini, Cloudflare Workers AI, Kaggle/Colab GPUs). At published paid prices the logged calls and GPU time would cost about $0.99, most of it the Wan clips (about 2 GPU-hours on a T4, including failed attempts). The binding limits were quotas and GPU access, not money. Measured per stage in [COSTS.md](COSTS.md).
- **Failures are classified** (transient / quota / daily quota / bad input / out of memory) and retried only when retrying can help. See [`pipeline/retry.py`](pipeline/retry.py).

## Setup

Requirements: Python 3.12, FFmpeg (a build with libass, e.g. `winget install Gyan.FFmpeg`).

```
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # (macOS/Linux: cp) then add your own keys; never commit .env
```

Keys needed (all free tiers): Google AI Studio (Gemini), Cloudflare Workers AI (account id + token with Workers AI permission), Kaggle (GPU notebooks).

The two GPU models (Wan 2.2 for motion, ACE-Step 1.5 for music) run in notebooks on a free GPU, not from this machine. `export` writes a self-contained notebook (sources in [`notebooks/`](notebooks/)); you run it on Kaggle or Google Colab (the notebook's first cell says how; the score was made on Colab, see [FAILURES F12](FAILURES.md)); `ingest` accepts only outputs whose job hash matches the current storyboard. See [`pipeline/kaggle.py`](pipeline/kaggle.py).
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
python -m pipeline assemble            # the final edit: both formats, measured against the brief
python -m pipeline narration --repair-c2pa   # one-time fix for lines recorded before F11
python -m pipeline all                  # the whole film (make film); finished stages come from cache
python -m pipeline costs                # rebuild COSTS.md from runs.jsonl
python -m pytest                        # tests (no network; the FFmpeg tests render real films at tiny size)
```

Outputs are committed under `outputs/`, so a fresh clone can rebuild from cache with `python -m pipeline all --offline` and no API keys. `--offline` forbids provider calls, not local FFmpeg work. A score that is not made yet does not stop `all`: the film is assembled with the placeholder bed, and the manifest records that it was.

**The films:** `outputs/assemble/film_9x16__<hash>.mp4` (1080x1920) and `film_16x9__<hash>.mp4` (1920x1080); the current ones are the paths under `stages.assemble` in `outputs/manifest.json`. They have with English subtitles burned in and also in `outputs/final/buna_en.srt`. After encoding, each film is measured again for duration, size, fps, loudness (LUFS) and true peak. The numbers are kept in `outputs/manifest.json` and `runs.jsonl`, and any miss against the brief is printed as `CHECK:`.

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
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the code works: stages, cache contract, logs, hand-offs, mastering |
| [COSTS.md](COSTS.md) | Calls, latency, GPU time and money, generated from `runs.jsonl` (`python -m pipeline costs`) |
