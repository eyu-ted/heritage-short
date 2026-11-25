# The Heritage Short: Master Plan (design on paper, before any code)

> Film: **"Buna" — the Ethiopian coffee ceremony**, narrated in **Amharic**, English subtitles, original score.
> Status: DESIGN ONLY. Nothing below has been built yet. Items marked **[VERIFY]** are facts I could not confirm and will be checked by the smoke test.
> Deadline: **Thu 26 Nov 2026, 23:59 EAT** (both assignments). Target: submit by ~18:00.

---

## 0. One-paragraph summary

We build a small studio in code. One file, `storyboard.json`, describes the whole film. Five scripts read it and each makes one kind of material: **narration, keyframes (stills), shots (motion), music, assembly (the edit)**. Every output is named by a hash of its inputs, so changing one shot regenerates only that shot. Every model call is logged to `runs.jsonl`. The film can always be finished from stills (Ken Burns pan/zoom); Wan video clips are an *upgrade*, not a dependency. A stranger can clone the repo, run one command, and get the film, because generated outputs are committed and the pipeline replays from cache without API keys.

---

## 1. The film

### 1.1 Why this story works for the pipeline
- **No faces needed.** The ceremony is hands, fire, smoke, steam, clay and cups. This removes identity drift and the consent gate for likeness.
- **Built-in 3-act structure.** The ceremony has three rounds of coffee — *abol*, *tona*, *baraka* — which gives the film its shape, its music cues and its ending.
- **Strong recurring motif.** The *jebena* (clay pot) and its arcing pour of coffee return at the end.
- **Honest risk:** hands are a known weak spot for image models. Mitigation: objects first (pot, cups, smoke, beans), hands only partial, backlit, out of focus or in motion; a recurring figure shown only from behind or as a silhouette.

### 1.2 Brief (to go in DESIGN.md)
- **Audience:** young Ethiopians and diaspora family, watching on a phone (vertical first), probably muted-then-unmuted in a feed.
- **Intent:** they should *slow down and feel belonging*: the ceremony is not about coffee, it is about time and being together.
- **Logline:** *Three small cups, three rounds, and nobody is left out.*
- **Language:** Amharic narration, English subtitles. **[VERIFY Amharic TTS quality first.]**
- The user supplies the **real personal anchor** (whose ceremony, which town, one true detail). The draft below uses placeholders; nothing about the family is invented.

### 1.3 Shot list (10 shots + end card, ~73 s)

| # | Round | Picture | Narration beat (English draft, to be rewritten with your real story) | Why this shot exists | Dur |
|---|---|---|---|---|---|
| 1 | Prologue | Dawn courtyard, fresh grass strewn on the floor, soft light | "Before the city wakes, the grass is spread." | Establish place and time | 7s |
| 2 | Prologue | Green beans washed in a clay bowl | "The day begins with beans, and patience." | First object; sets slow pace | 7s |
| 3 | Abol | Beans roasting in a pan over charcoal, smoke rising | "Fire, and the smell that calls the neighbours." | Sensory hook; motion = smoke | 7s |
| 4 | Abol | Incense smoke curling, backlit | "Smoke carries our welcome." | Mood; no hands needed | 6s |
| 5 | Abol | Mortar and pestle grinding, close-up | "The grinding is the first music of the day." | Rhythm; links to the score | 6s |
| 6 | Tona | Jebena on coals, steam | "Then we wait. Waiting is part of the gift." | Pacing breath; stillness | 7s |
| 7 | Tona | **Hero shot:** the pour arcing from the jebena into small cups | "One pot. Many cups. No one is left out." | The emotional centre and motif | 8s |
| 8 | Baraka | Elder seen from behind in a white netela, offering a cup toward camera | "Three rounds: abol, tona, baraka." | The human presence, without a face | 7s |
| 9 | Baraka | Row of cups on a tray, steam rising, empty chairs warm with light | "The third round is the blessing." | Emotional peak; implied community | 7s |
| 10 | Close | Door opens onto morning light; echo of shot 1 | "Stay a little longer. The coffee is still warm." | Closing motif, answers shot 1 | 8s |
| E | — | End card: "Made with AI", title, credits | (none) | Mandatory deliverable | 3s |

Rule: **one idea, one gentle movement per shot.** Subject centred so the same picture survives both 9:16 and 16:9 crops.

### 1.4 Narration budget
- Roughly 9–10 short lines, ~45 s of speech inside ~70 s of film; the rest is music and silence.
- English guide is 2–2.5 words/s; **Amharic rate is unknown, so we measure from real TTS output** and let the measured durations set shot lengths (the radio cut decides timing).

---

## 2. System architecture

```
                    ┌──────────────────────────┐
                    │      storyboard.json     │  ← the contract
                    │  validated by schema/    │
                    └────────────┬─────────────┘
         ┌───────────┬───────────┼────────────┬────────────┐
         ▼           ▼           ▼            ▼            ▼
   1 narration  2 keyframes  3 shots      4 music     (validate)
   Gemini TTS   Cloudflare   Wan 2.2 on   ACE-Step     schema +
   per shot     FLUX         Kaggle  OR   on Kaggle    consistency
   → .wav       → .png       Ken Burns    → .wav       checks
                             → .mp4
         └───────────┴───────────┴────────────┘
                              ▼
                       5 assemble (FFmpeg)
         cut to narration · duck music · burn subtitles ·
         loudnorm · end card · reframe
                              ▼
              film_9x16.mp4        film_16x9.mp4

   Every stage: cache-by-hash · retries · logs a line to runs.jsonl
```

### 2.1 Design principles
1. **One contract.** Stages never talk to each other, only to `storyboard.json` and to files in `outputs/`.
2. **Idempotent and resumable.** Re-running does nothing if inputs did not change.
3. **A floor that cannot fail.** Stills + narration + music + subtitles is a complete film.
4. **Log everything, invent nothing.** COSTS, EXPERIMENTS and FAILURES are written from real logs.
5. **Secrets only in `.env`** (git-ignored). `.env.example` is committed.

### 2.2 Repository layout
```
heritage-short/
  README.md              one-command run, what it does, what it costs
  PLAN.md                this document (becomes ARCHITECTURE.md content)
  storyboard.json        THE contract
  schema/storyboard.schema.json
  pipeline/
    __main__.py          CLI entry: python -m pipeline <stage|all>
    config.py            paths, env, model ids
    storyboard.py        load + validate + derive durations
    hashing.py           canonical JSON → sha256 cache keys
    cache.py             manifest + hit/miss logic
    runlog.py            append to runs.jsonl
    retry.py             backoff, error classification, fallback policy
    narration.py  keyframes.py  shots.py  music.py  assemble.py
    providers/           gemini.py  cloudflare.py  (thin API wrappers)
  notebooks/
    wan_shots.ipynb      Kaggle: image→video, resume-safe
    ace_step_music.ipynb Kaggle: music candidates
  outputs/               kept in git: narration/ keyframes/ shots/ music/ final/
  runs.jsonl             one line per model call
  tests/                 hashing, caching, schema, subtitle timing
  DESIGN.md ARCHITECTURE.md EXPERIMENTS.md FAILURES.md COSTS.md ETHICS.md
  Makefile  .env.example  .gitignore  requirements.txt
```

### 2.3 The one command
- `make film` → `python -m pipeline all`
- `make` is not installed on this Windows machine, so the README documents **`python -m pipeline all`** as primary, with `make film` as an alias. Both validate first, then run narration → keyframes → shots → music → assemble.
- Useful flags: `--shot s07` (one shot only), `--force` (ignore cache), `--dry-run` (show what would run, no API calls), `--offline` (use cache only; fail clearly if something is missing).
- A stranger with **no API keys** gets the full film from committed outputs. With keys, they can regenerate anything.

---

## 3. The contract: `storyboard.json`

Prompts and seeds live **in the file, not in code**, so a run is reproducible and explainable.

```jsonc
{
  "project": {
    "title": "Buna", "language": "am", "subtitle_language": "en",
    "audience": "...", "intent": "...",
    "fps": 24, "outputs": ["9x16", "16x9"], "reframe": "center_crop"
  },
  "style_block": "hand-painted, warm, soft film grain, ...",   // appended to every image prompt
  "references": [ { "id": "figure", "description": "elder seen from behind in white netela ..." },
                  { "id": "props",  "description": "jebena, sini cups, rekebot tray ..." } ],
  "shots": [{
    "id": "s07", "order": 7, "round": "tona",
    "reason": "Emotional centre; the pour is the motif",
    "narration": { "am": "...", "en": "...", "voice": "<named voice>", "style": "calm, warm, unhurried" },
    "keyframe": { "prompt": "...", "seed": 4242, "refs": ["props"], "size": [1344, 768] },
    "motion":   { "backend": "wan", "prompt": "the stream of coffee arcs; camera fixed",
                  "seed": 7, "fallback": "kenburns", "kenburns": { "zoom": 1.08, "pan": "left" } },
    "min_duration_s": 7
  }],
  "music": { "cues": [ { "id": "c1", "round": "abol", "caption": "...", "bpm": 72, "instrumental": true, "seed": 11 } ],
             "chosen": "c1-seed11" },
  "mix": { "duck": { "threshold": 0.02, "ratio": 6, "attack_ms": 300, "release_ms": 1500 },
           "loudness": { "I": -14, "TP": -1 } },
  "endcard": { "text": "Made with AI", "duration_s": 3 }
}
```

The JSON Schema enforces: 8–12 shots, unique ids, a non-empty `reason` on every shot, required prompts/seeds, allowed backends, and a total-duration check (60–90 s) that runs after narration timings are known.

---

## 4. Stage contracts

| Stage | Reads | Writes | Provider | Cache key includes |
|---|---|---|---|---|
| **validate** | storyboard.json | pass/fail | local | n/a |
| **narration** | shot.narration | `outputs/narration/<id>.wav` + duration | Gemini TTS **[VERIFY model id, Amharic]** | text, voice, style, language, model |
| **keyframes** | style_block, references, shot.keyframe | `outputs/keyframes/<id>.png` | Cloudflare FLUX **[VERIFY klein vs schnell, size support]** | prompt+style, seed, size, model, steps, ref hashes |
| **shots** | keyframe png, shot.motion | `outputs/shots/<id>.mp4` | Kaggle Wan 2.2 TI2V-5B, or local Ken Burns | keyframe **file hash**, motion prompt, seed, resolution, model |
| **music** | music.cues | `outputs/music/<cue>-<seed>.wav` | Kaggle ACE-Step 1.5 | caption, bpm, key, duration, seed, model |
| **assemble** | all of the above + mix/endcard | `outputs/final/film_*.mp4`, `.srt` | local FFmpeg | hashes of every input artifact + mix settings |

**Dependency rule:** a stage's cache key includes the *hash of the upstream file*, not just the upstream prompt. If a keyframe changes, its shot regenerates automatically; the other nine do not.

### 4.1 Cache and manifest
- `hashing.py`: canonical JSON (sorted keys, normalised floats) → sha256 → first 12 hex chars.
- `outputs/manifest.json`: `shot_id → {stage → {hash, path, status, produced_at}}`.
- Cache outcomes are logged as `status: "cache_hit"`, which is how the walkthrough can prove "only one shot regenerated".

### 4.2 `runs.jsonl` — one line per model call
```json
{"ts":"...","run_id":"...","stage":"keyframes","shot_id":"s07","provider":"cloudflare",
 "model":"@cf/black-forest-labs/flux-1-schnell","params":{"steps":4,"size":[1344,768]},
 "seed":4242,"input_hash":"a1b2c3d4e5f6","output":"outputs/keyframes/s07.png",
 "latency_ms":2140,"status":"ok","attempt":1,"error":null,
 "cost":{"unit":"neurons","amount":38.4,"list_price_usd":0.0004},"gpu_minutes":null}
```
Statuses: `ok`, `error`, `cache_hit`, `fallback`. Kaggle runs log `gpu_minutes` from timings the notebook records.

### 4.3 Reliability policy
- **Retries:** exponential backoff with jitter, max 3 attempts per call.
- **Error classes:** quota/rate-limit (wait or stop and log), transient network (retry), bad input (fail fast), out-of-memory (switch to lower resolution/offload, then fallback).
- **Fallback chain for a shot:** Wan clip → retry with simpler prompt → Ken Burns on the keyframe. The fallback is logged and shown in FAILURES.md; the build never blocks.
- **Daily quota guard:** keyframes stage counts neurons used today and stops cleanly before the limit, resuming next run.
- **No secrets in logs:** keys are never written to `runs.jsonl`.

---

## 5. Stage design details

### 5.1 Narration
- One WAV per shot, generated line by line so re-takes are cheap.
- Fixed voice, short style instruction ("calm, warm, unhurried"). Preset voice only — **no voice cloning**.
- Measured with `ffprobe`; shot length = `max(min_duration_s, narration_len + 1.0 s)`.
- Amharic text is checked by a native speaker (names, ejectives, pacing).
- English subtitle text is stored beside each line in the storyboard.

### 5.2 Keyframes
- **Reference sheet first:** a style board, the recurring figure (from behind, white netela with a coloured border), and a props sheet (jebena, sini cups, rekebot tray, mukecha, pan). Generate 4 options each, pick one; the pick is recorded (EXPERIMENTS entry).
- Every keyframe prompt = shot prompt + style block + reference descriptions. Image-reference conditioning is used only if the chosen model supports it **[VERIFY]**; otherwise consistency comes from the style block, fixed seeds and descriptions.
- Composition rule: subject centred, safe margins, for dual-ratio crops.
- A quick human check for hands/artifacts before spending GPU time. Keyframes are approved shot by shot.
- Text in images is never requested; titles and subtitles are added in code.

### 5.3 Shots (motion)
- **Wan 2.2 TI2V-5B on Kaggle**, image-to-video. Prompt describes only motion and camera ("the stream arcs into the cups; camera fixed").
- Draft at 480p first, finish only chosen shots at higher resolution.
- T4 specifics **[VERIFY]**: fp16 (no bf16), model/CPU offload, expect minutes per clip.
- Notebook is **resume-safe**: reads a job list, writes each MP4 as it finishes, records per-clip latency and GPU seconds, skips finished jobs after a timeout.
- Clip length ≈ 5 s. If a shot is longer, the clip is followed by a slow Ken Burns on its last frame with a crossfade.
- Pipeline flow: `shots` computes cache misses → writes `kaggle/jobs.json` and prepares the keyframes folder → you run the notebook → you download MP4s into `outputs/shots/` → `python -m pipeline shots --ingest` verifies hashes and logs the entries. (Semi-manual by design; documented honestly in ARCHITECTURE.md.)
- Shots with no clip yet use Ken Burns automatically.

### 5.4 Music
- **ACE-Step 1.5 on Kaggle**, instrumental, 3 candidates, chosen by ear listening *under* the narration at low volume; reason written in EXPERIMENTS.
- Caption idea: *"Ethiopian-inspired acoustic instrumental, plucked lyre (krar), soft bowed fiddle (masenqo), warm, intimate, slow, gentle texture, no lead melody"*; tempo and key go in the metadata fields, not in the caption.
- Cue plan follows the ceremony: Abol (sparse, warm) → Tona (small build, soft hand percussion) → Baraka (return to the opening theme, resolve).
- 30–60 s is the stable length; if one track cannot cover the film, we test one longer generation vs. two joined sections (experiment).

### 5.5 Assembly (FFmpeg only, deterministic)
1. Per shot: use the Wan clip if present, else Ken Burns from the keyframe, at the measured shot length.
2. Concatenate shots (short crossfades; fade to black at the end).
3. Narration track: shot WAVs placed at each shot's start + small offset.
4. Music: loudness-match each stem first, then **sidechain duck** the music with the narration (`threshold 0.02, ratio 6, attack 300 ms, release 1500 ms`, tuned by ear).
5. **Subtitles:** SRT generated from English text and real narration timings; ≤2 lines, ~40 chars/line; burned in and kept inside the vertical safe area. Amharic is not burned in (avoids font risk; English subtitles are what the brief requires).
6. End card (2–3 s): "Made with AI" plus title, drawn in FFmpeg/Pillow (no Node/Remotion needed).
7. **Final loudness:** two-pass `loudnorm` to about −14 LUFS, true peak ≈ −1 dB.
8. Export **both** ratios, H.264 + AAC MP4, constant 24 fps.
9. **Reframe strategy** is configurable: `center_crop` (default) vs `blur_pad` (16:9 video centred over a blurred 9:16 backdrop). Compared as an experiment.
10. Do not strip any AI provenance metadata that tools add.

---

## 6. Design thinking and user tests (graded)

| Step | What | Evidence in repo |
|---|---|---|
| Brief | Audience, where they watch, one feeling — written **before generating** | DESIGN.md |
| **Test 1 — radio cut** | Amharic narration over placeholder music on black; ≥3 people from the audience (in person or Slack) | DESIGN.md: who (initials), what they said, what changed |
| Change | The storyboard visibly changes (e.g. cut a line, reorder a beat, adjust pacing) | git diff of storyboard.json |
| **Test 2 — near-final cut** | ≥3 people again; includes a native-speaker pronunciation check | DESIGN.md |

Questions to ask (think-aloud): *What did you picture? Which line did you feel? Where did you get lost? Was the pace right? Did any word sound wrong?*

---

## 7. Experiments (target ≥10, each: hypothesis → change → result, one change at a time, seed fixed)

1. Amharic vs English TTS quality (name/ejective check)
2. TTS style instruction vs none
3. Style block vs no style block on consistency of 3 keyframes
4. Fixed seed vs varied seed across the props
5. FLUX.1 schnell vs FLUX.2 klein (if available): quality, latency, neurons
6. Wan 480p vs 720p: time, GPU minutes, quality
7. Wan fp16+offload settings vs OOM behaviour on T4
8. Wan clip vs Ken Burns on the same shot (blind preference, ≥5 people if time)
9. ACE-Step caption variants / 3 candidates; choice rationale
10. Ducking settings (threshold/release) by ear
11. Vertical reframe: center_crop vs blur_pad

Each entry is written from real runs and links to `runs.jsonl` lines.

---

## 8. Measurement (COSTS.md, from logs)
- Per stage: latency (median/total), API units (neurons, tokens), Kaggle GPU minutes.
- **List-price equivalent:** what the same calls would cost at published prices (TTS per audio token, Cloudflare per 1k neurons, a GPU hourly rate) **[fill from the live pricing pages on the day]**.
- Quotas actually observed (what the free tiers really allowed), noted as dated findings.

---

## 9. Ethics (ETHICS.md)
- **No real person's face or likeness** appears. The figure is a stylised fictional silhouette.
- **No voice cloning.** A preset TTS voice only.
- The story's source (the relative or elder who shared the tradition) gives a **recorded verbal or written consent** for their story to be used; stored as a note with date and wording.
- Licences table: Wan 2.2 (Apache 2.0), ACE-Step 1.5 (MIT; outputs usable commercially), FLUX.1 schnell (Apache 2.0), FLUX.2 klein 4B (Apache 2.0) / 9B (non-commercial), Gemini and Cloudflare terms **[VERIFY each on the day]**.
- Labelling: end card + platform AI-disclosure toggle on posting; provenance metadata left intact.
- Privacy: no private family details sent to free endpoints that may train on inputs.

---

## 10. Deliverables checklist mapped to the rubric

**Assignment 1 (code + report, 100 pts)**
- [ ] Schema-validated storyboard, stage boundaries, caching, retries, no secrets, complete runs.jsonl, one command (20)
- [ ] README + ARCHITECTURE.md (10)
- [ ] DESIGN.md with two user tests and visible storyboard change; reason per shot (10)
- [ ] ≥10 experiments (10)
- [ ] FAILURES.md with real blockers (10)
- [ ] COSTS.md measured + list-price equivalent (5)
- [ ] ETHICS.md consent, licences, labelling (5)
- [ ] Report: audience reflection (10) · practices tested honestly: one that beat my instinct, one that did not (10) · curiosity beyond the floor (10)
- [ ] AI interview prep: reread my own logs

**Assignment 2 (manual, 100 pts)**
- [ ] 9:16 MP4 (main link) + 16:9 MP4, 60–90 s, ducked score, accurate subtitles, end card (50)
- [ ] Walkthrough ≤5 min: architecture, one hard decision, change one keyframe prompt or narration line → rerun → only that shot regenerates, logs shown (30)
- [ ] Public post with AI label, written by me (20)
- [ ] All links open without a login

---

## 11. Environment setup (needed before step 1 of coding)
Found on this machine: Git ✔, Python **3.15.0** (very new; some wheels may be missing). Missing: **FFmpeg, make, Node, gh, GPU**.
- Install **FFmpeg** (a build with libass for subtitles) via `winget`.
- Install **Python 3.12** alongside 3.15 for safe wheels; use a venv.
- Libraries (kept minimal): `jsonschema`, `httpx`, `python-dotenv`, `google-genai`, `Pillow`, `pytest`.
- `make` is optional; the README documents the Python command.
- Accounts the user must create: Google AI Studio key, Cloudflare account + API token + account id, Kaggle (phone-verified). Keys go in `.env` only.

---

## 12. Time plan (≈1.5 days)

**Block A — today (Wed 25 Nov)**
1. Install tools, repo skeleton, `.env`, `.gitignore`.
2. **Smoke test** each provider once → first `runs.jsonl` lines (answers: Amharic TTS? klein? neurons per image?).
3. Story anchor + consent note; DESIGN.md brief.
4. Schema + draft storyboard; validate.
5. Narration + **radio cut**; user test 1; revise storyboard.
6. Reference sheet → keyframes; start the Kaggle Wan job; start music candidates.

**Block B — tomorrow (Thu 26 Nov)**
7. Ingest clips + music; assembly; both exports.
8. User test 2; fix.
9. README, ARCHITECTURE, COSTS, EXPERIMENTS, FAILURES, ETHICS; report.
10. Post with AI label; record walkthrough; **submit both assignments by ~18:00**.

**Cut order if time slips:** extra experiments/ceiling work → Wan for most shots (keep 2–3 hero clips: s03, s07, s10) → blind preference test. Never cut: both ratios, subtitles, ducking, end card, consent, user tests, logs.

---

## 13. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Amharic TTS poor | Medium | Test first; native-speaker review; document as FAILURES evidence; fall back to English narration |
| Cloudflare free plan excludes my FLUX model / daily limit | Medium | Try schnell vs klein; quota guard; batch; keep prompts planned |
| Wan too slow / OOM on T4 | High | 480p drafts, offload, resume-safe notebook, Ken Burns fallback, 2–3 hero clips only |
| Hands look wrong | High | Objects-first shots; partial, backlit, silhouette; per-keyframe check |
| Kaggle quota / phone verification delay | Medium | Start verification immediately; Colab as backup |
| Style inconsistency across shots | Medium | One style block, fixed seeds, reference descriptions, approval per keyframe |
| Time overrun | High | Floor-first design; explicit cut order |
| Provider names/limits differ from the brief | High | Smoke test logs what is real; record in COSTS/FAILURES |

---

## 14. What is NOT in scope now
Prompt-to-film product for arbitrary users, web app, MCP server, LoRA training, extra languages, Remotion. These are "raising the ceiling" ideas for later, and only if the floor is complete.

## 15. What I will and will not do
- I write the code, notebooks, schema and doc scaffolding, and explain each part so you can defend it in the interview.
- I will **not** fabricate user tests, experiment results, costs or logs. Those sections are filled only from real runs and real people.
- You do: choose the personal anchor, record consent, create accounts and paste keys, run the Kaggle notebooks, run the two user tests, check Amharic pronunciation, post publicly, record the walkthrough and submit.
