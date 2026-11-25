# Implementation Steps (companion to PLAN.md)

How to read this: each step has **Build** (what I write), **You** (what only you can do), **Done when** (a check we can run or see), and a rough time. We do **one step at a time**, verify it, then move on. Gates (⛔) are decision points where the result changes the plan.

Legend: 🤖 = I do it · 🧑 = you do it · ⏳ = long wait (start early, do other things meanwhile)

---

## Phase 0 — Setup (≈45 min)

**S0.1 Tools** 🤖 (you approve installs)
- Build: install FFmpeg (with libass) and Python 3.12 via winget; create a venv.
- Done when: `ffmpeg -version` shows libass; `python --version` in the venv is 3.12.

**S0.2 Repo skeleton** 🤖
- Build: `git init`, folders from PLAN §2.2, `.gitignore` (ignores `.env`, venv, caches), `.env.example`, `requirements.txt`, `Makefile`, README stub, empty module files, `pytest` wired.
- Done when: `pytest` runs (0 tests pass, no errors); `git status` clean after first commit.

**S0.3 Accounts and keys** 🧑 ⏳ (start first, in parallel with S0.1)
- You: Google AI Studio key · Cloudflare account + API token + account id · Kaggle account with phone verification.
- Done when: keys are in `.env` (never pasted into chat or committed); Kaggle shows GPU option enabled.

---

## Phase 1 — Engine with no models (≈1.5 h)

**S1.1 Hashing, cache, run log** 🤖
- Build: `hashing.py` (canonical JSON → sha256), `cache.py` (manifest hit/miss), `runlog.py` (append to `runs.jsonl`).
- Done when: tests prove same input → same hash, changed input → different hash, a log line is valid JSON.

**S1.2 Retry and error policy** 🤖
- Build: `retry.py` with backoff, error classes (quota / transient / bad input / OOM), max 3 attempts.
- Done when: tests with a fake flaky function show retries, then a clean failure, never an infinite loop.

**S1.3 Schema + storyboard loader** 🤖
- Build: `schema/storyboard.schema.json`, `storyboard.py`, and a first draft `storyboard.json` with 10 shots (prompts and reasons, narration still placeholder).
- Done when: valid file passes; tests show failure for 13 shots, missing `reason`, duplicate ids, unknown backend.

**S1.4 CLI skeleton** 🤖
- Build: `python -m pipeline validate | all --dry-run | <stage> --shot <id> | --force | --offline`.
- Done when: `--dry-run` prints a 10-row plan of what *would* run.

✅ **Checkpoint A:** engine works end to end with zero API calls.

---

## Phase 2 — Smoke test: find out what is real (≈45 min)

**S2.1 Provider wrappers** 🤖
- Build: `providers/gemini.py`, `providers/cloudflare.py` (thin, logged, retried; keys from `.env`, never logged).

**S2.2 `python -m pipeline smoke`** 🤖 → 🧑 runs it
- Build: one text call, one Amharic TTS sample, one image call; each logs latency/units to `runs.jsonl`; lists available model ids.
- You: run it, and **listen to the Amharic sample** (or send it to a native speaker).
- Done when: we have a written facts table: valid model ids, Amharic OK or not, image size support, neurons per image.

⛔ **Gate 1 — decide from the facts:**
- Amharic good → continue as planned. Poor → document in FAILURES.md and choose: English narration with Amharic title, or retest another voice.
- FLUX.2 klein free? Else FLUX.1 schnell.
- Update the **[VERIFY]** items in PLAN.md.

**Gate 1 result (25 Nov, smoke runs `94a69d` to `0bf4bd`):**
- Narration: **Amharic** with `gemini-3.8-flash-tts` (API v1beta), voice `Sulafat`, style in `speech_metadata`. Approved by a native speaker.
- Keyframes: **FLUX.2 klein-4b** (Apache 2.0) on Cloudflare: honours size (1344x768) and accepts up to 4 reference images. FLUX.1 schnell kept only as a fallback (no seed, no size).
- Seeds do **not** reproduce images on Cloudflare (E2) → keep approved images; consistency comes from reference images.
- Gemini text is unreliable right now (503/429) → Amharic lines written/reviewed by the user; Gemini is an optional helper.
- Free Gemini TTS quota is tight (429 after ~16 calls) → cache every narration line; no needless smoke reruns.
- Kaggle token works.

---

## Phase 3 — Story and the radio cut (≈2.5 h)

**S3.1 Personal anchor and consent** 🧑 + 🤖
- You: give the real anchor (whose ceremony, which town, one true detail); get verbal/written consent from the person whose story it is.
- Build: `DESIGN.md` brief (audience, intent, where they watch, feeling) and the first `ETHICS.md` consent entry — written *before* anything is generated.

**S3.2 Narration script** 🤖 → 🧑
- Build: draft the lines in English, translate to Amharic with Gemini, save both in `storyboard.json`.
- You (or a native speaker): correct the Amharic wording and tone.
- Done when: every shot has `narration.am` and `narration.en`, and the schema passes.

**S3.3 Narration stage** 🤖
- Build: `narration.py` (one WAV per shot, cached, durations from ffprobe, shot lengths derived).
- Done when: second run prints all `cache_hit`; total duration estimate is inside 60–90 s.

**S3.4 Radio cut** 🤖
- Build: `assemble --radio` (narration over a generated placeholder pad on black).
- Done when: `radio_cut.mp4` plays end to end.

**S3.5 User test 1** 🧑
- You: play it to ≥3 people from the audience; record initials, what they said, what you will change in DESIGN.md. Then I change `storyboard.json` accordingly (the git diff is the evidence).

✅ **Checkpoint 1:** radio cut plays; DESIGN.md has test 1.

---

## Phase 4 — Pictures (≈2.5 h)

**S4.1 Reference sheet** 🤖 → 🧑
- Build: `keyframes --refs` makes 4 options each of style board, elder-from-behind, and props.
- You: pick one of each; I record the choice and reason (first EXPERIMENTS entry).

**S4.2 Keyframes for all shots** 🤖 → 🧑
- Build: `keyframes.py` with the quota guard (stops before the daily limit, resumes next run), caching, seeds from the storyboard.
- You: approve each image; regenerate with `--shot sNN` where hands/objects look wrong.
- Done when: 10 approved PNGs in `outputs/keyframes/`.

**S4.3 Ken Burns backend (the floor)** 🤖
- Build: local FFmpeg `zoompan` motion for every shot as the guaranteed fallback.
- Done when: a silent animatic of 10 shots plays.

⏳ **Start the Kaggle jobs as soon as S4.2 produces approved keyframes** (Phases 5 and 6 run in the background while I build Phase 7).

---

## Phase 5 — Music (≈1 h of my work, then waiting)

**S5.1 Music notebook** 🤖 → 🧑 ⏳
- Build: `notebooks/ace_step_music.ipynb` + job list (3 candidates, instrumental, tempo/key in metadata).
- You: run on Kaggle, download WAVs into `outputs/music/`.

**S5.2 Ingest and choose** 🤖 → 🧑
- Build: ingest command that verifies files and logs the entries.
- You: listen under the narration at low volume and choose; I write the reason into EXPERIMENTS.md.

---

## Phase 6 — Motion with Wan (≈1.5 h of my work, then waiting)

**S6.1 One-shot test first** 🤖 → 🧑 ⏳
- Build: `shots.py` job export + `notebooks/wan_shots.ipynb` (fp16, offload, 480p draft, resume-safe, records latency and GPU seconds).
- You: run only **s07 (the pour)** first. Done when it finishes without OOM and we know minutes per clip.

⛔ **Gate 2 — budget:** from the measured clip time, decide how many shots Wan can cover (hero shots s03, s07, s10 first).

**S6.2 Ingest and batch** 🤖 → 🧑 ⏳
- Build: `shots --ingest` verifies hashes, logs `gpu_minutes`, falls back to Ken Burns for missing clips.
- You: run the batch for the chosen shots.

---

## Phase 7 — Full assembly (≈3 h, while Kaggle runs)

**S7.1 Picture edit** 🤖: clip-or-Ken-Burns per shot, crossfades, fade to black.
**S7.2 Audio mix** 🤖: place narration, loudness-match stems, sidechain ducking, two-pass loudnorm.
**S7.3 Subtitles** 🤖: SRT from real timings, ≤2 lines/≈40 chars, burned in, inside the vertical safe area.
**S7.4 End card** 🤖: "Made with AI" + title, 3 s.
**S7.5 Exports and checks** 🤖: 9:16 and 16:9 MP4 (H.264/AAC, 24 fps), reframe option; a check script prints duration, resolution, fps and measured LUFS/true peak.
- Done when: both MP4s are 60–90 s, around −14 LUFS, peak ≤ −1 dB.

✅ **Checkpoint 2:** rough cut with a picture for every shot and the chosen score.

---

## Phase 8 — Test 2 and hardening (≈2 h)

**S8.1 User test 2** 🧑: ≥3 people plus a native Amharic pronunciation check; I apply the fixes.
**S8.2 Clean-clone test** 🤖 → 🧑: clone into a fresh folder, run `python -m pipeline all` without keys; confirm it rebuilds from cache. Then change one narration line and confirm **only that shot regenerates** (this is the walkthrough demo).
**S8.3 Secrets scan** 🤖: confirm no keys in git history or outputs.

---

## Phase 9 — Docs, release, submit (≈4 h)

**S9.1 Evidence docs** 🤖: a script summarises `runs.jsonl` into the COSTS table (latency, units, GPU minutes, list-price equivalent); I write EXPERIMENTS.md and FAILURES.md **only from real logs and real events**.
**S9.2 README, ARCHITECTURE.md, ETHICS.md final** 🤖.
**S9.3 Public GitHub** 🧑 (+🤖): create the public repo, push, check file sizes (GitHub 100 MB limit), confirm README works from a stranger's view.
**S9.4 Report** 🤖 drafts → 🧑 rewrites in your voice (it must show your own judgment): audience learnings, hardest problem, one practice that beat your instinct and one that did not, what next.
**S9.5 Release** 🧑: upload both films, post publicly with the AI label (you write the post), record the ≤5 min walkthrough (I prepare a script and a shot list).
**S9.6 Submit** 🧑: Assignment 1 (repo + report), then Assignment 2 (9:16 main link + 16:9 + walkthrough + post). Open every link in a private window to confirm no login is needed. Then prepare for the AI interview by rereading your logs.

---

## Parallel tracks (how we beat the clock)

```
Time →  [Phase 0-2 setup/engine/smoke] → [3 story+radio cut] → [4 keyframes] ─┬→ [7 assembly]──→[8 test2]→[9 release]
                                                                              ├→ ⏳ 5 music (Kaggle)  ─┘
                                                                              └→ ⏳ 6 Wan (Kaggle)    ─┘
You, in parallel:  accounts ▸ consent ▸ Amharic review ▸ user test 1 ▸ approve images ▸ run notebooks ▸ user test 2 ▸ post/record/submit
```

## Rules for every step
1. One step at a time; I show what changed and how to check it before the next step.
2. Tests or a visible check before "done".
3. Small commits per step (I will ask before committing).
4. If a step fails, it goes into FAILURES.md immediately, with what we tried.
5. Nothing fabricated: logs, tests with people, costs and experiments come only from real runs.

## Hard "never cut" list
Both aspect ratios · English subtitles · ducked score · end card · consent record · two user tests · `runs.jsonl` · one-command run · public post with AI label.

## First move (when you say go)
S0.1 and S0.2 together, while you start S0.3 (accounts and the Kaggle phone verification).
