# Experiments

Format: **hypothesis → change → result → decision**. One change at a time; evidence in `runs.jsonl` (run ids).

---

## E1. Where does the TTS style instruction go?
- **Hypothesis:** putting the style in front of the line ("Speak slowly, warmly...: <line>") makes Gemini TTS speak the instruction aloud instead of only using it as direction.
- **Setup:** model `gemini-3.8-flash-tts`, voice `Sulafat`, same English line ("One pot. Many cups. No one is left out."), only the style placement changes.
- **Result (measured audio length):**

| Run | Style placement | Audio |
|---|---|---|
| `2454ce` | prefixed into the text | **13.56 s** |
| `2454ce` | none | 4.76 s |
| `61b7c3` | `speech_metadata.style` (separate field) | **6.32 s** |
| `61b7c3` | none | 4.12 s |

  The prefixed version was ~2.8x the unstyled length; in the separate field it is ~1.5x, which fits "slower and warmer" rather than "extra words spoken". Amharic sample: 13.13 s prefixed vs 4.76 s with `speech_metadata`.
- **Decision:** style always goes in `speech_metadata`. To confirm by ear: `outputs/smoke/tts_en.wav` and `tts_en_nostyle.wav`.
- **Gate 1 (25 Nov):** the user, a native Amharic speaker, listened to `outputs/smoke/tts_am.wav` (`gemini-3.8-flash-tts`, voice `Sulafat`, style in `speech_metadata`) and judged it **correct and well pronounced**. Decision: narrate in Amharic as planned.
- **Still open:** does the style instruction improve the Amharic delivery compared with no style? (Future entry, native listener, blind A/B.)

## E2. Does the same seed reproduce the same image on Cloudflare FLUX.2 klein-4b?
- **Hypothesis:** with the same prompt, seed (1007) and size (1344x768), klein-4b returns the same image, so seeds can be used for fair A/B prompt tests and for reproducibility.
- **Change:** none between the two calls (run `0bf4bd`, `image_klein4b_a.jpg` vs `image_klein4b_b.jpg`).
- **Result:** **different images.** Mean absolute pixel difference 48/41/31 (R/G/B, out of 255); on 32x18 thumbnails still 35, i.e. a different composition, not noise. Image A shows a pot pouring from a spout over a tray; image B a large urn with a pestle in it.
- **Decision:**
  1. Seeds do not pin images on this endpoint, so "regenerate to get the same image" is impossible. Approved images must be kept, and the cache must only regenerate when inputs change (it already works that way).
  2. Seeds stay in the storyboard and the log for the record, but prompt A/B tests need several samples per variant, not one fixed seed.
  3. Consistency has to come from **reference images** (klein accepts up to 4) and the fixed style block.

## E3 (observation, to turn into an experiment in Phase 4). Is the prop vocabulary understood?
- **Observation:** in both klein images the style matches the brief (hand-painted, warm, earthy, grass on the floor), but **neither draws a real jebena** (A: a teapot shape; B: an urn), and the cups have handles although the prompt says "handleless".
- **Hypothesis for Phase 4:** a reference image of a correct jebena and sini cups (chosen from generated options) passed as `input_image_0` will fix the props more reliably than more words in the prompt.
- **Step 1 result (reference sheet, 25 Nov):** I split the vague "props" reference into separate, precise descriptions (jebena: round body, upright neck, handle, spout from the shoulder, "not a teapot, no lid, not a vase"; sini: "NO handles, like tiny bowls") and generated 4 options each on a plain background (`outputs/refs/contact_sheet.jpg`, 12 images, klein-4b at 1024x1024).
  - jebena: **2 of 4 correct** (opt1, opt2). opt3 and opt4 have no spout and read as vases.
  - sini: **4 of 4 handleless**, against 0 of 2 in the smoke test.
  - figure (from behind, white netela with tibeb): 4 of 4 from behind; opt2 turns enough to show part of the face, which breaks the no-likeness rule.
  - So precise description + isolated reference fixed the cups completely and the jebena half the time. Generating several options and picking one (as the brief suggests) is what makes it reliable. Step 2 (does passing the picked image into keyframes keep the props right in a full scene?) is measured on s06-s10.

## E6 (observation). First keyframes without references (s01-s05)
- **Result:** style consistent across all five (hand-painted, warm, earthy). Two problems a human review caught before any GPU time was spent animating them:
  - s05: a **disembodied hand** floats above the pestle (the "hands" weak spot the brief warns about).
  - s01: the grass reads as a growing lawn, not fresh grass strewn on the floor for the ceremony.
- **Decision:** retake both with prompt changes (s05: no hands in frame; s01: grass blades scattered on an earthen floor), bumping `keyframe.take` so take 1 is kept for comparison.
- **Result (take 2):** both fixed. s05 has no hands; s01 shows grass strewn on an earthen floor. Only those two shots were regenerated; s02-s04 stayed cached (the cache key includes `take`).

## E7. Reference images in full scenes: they fix the object, and copy the backdrop
- **Hypothesis (E3 step 2):** passing the picked reference images (jebena opt1, sini opt1, figure opt1; the author's picks) as klein `input_image_N` keeps the props right inside full scenes.
- **Result, take 1 (s06-s10):**
  - s06 and s10: **the jebena matches the reference** (neck, handle, spout) inside real scenes.
  - s07, s08, s09: the model copied the reference sheet's **plain cream backdrop** too. s09 was essentially the reference again (a tray on white); s07 showed one cup instead of many; s08 put the figure in an empty white room.
- **Change (take 2, s07-s09 only):** describe the room in the shot's own prompt ("inside a warm, dim room with earthen walls and fresh grass strewn on the floor") and say "the reference images give only the look of the objects; the setting is the room described, never a plain backdrop". Put in the shots' prompts, not the shared prompt builder, so the good s06/s10 stayed cached.
- **Result, take 2:** backdrops fixed in all three; s09 became the intended shot (cups, popcorn basket, empty stools, room). But s07 poured from the bottom of the pot, not the spout, and the front cup had a handle.
- **Take 3 (s07, last attempt under a 3-takes rule):** closer framing and the physics spelled out ("flows OUT OF ITS SPOUT", "every cup ... NO handle"). Result: correct jebena, pour from the spout, all cups handleless, many cups on the tray, room setting.
- **What I learned:** reference images are the strongest tool for *what* an object looks like, but they also pull the reference's composition along. Reference sheets should be made on a plain background (so they are clean references) **and** every scene prompt must state its own setting.
- **Cost of the look-development loop:** 12 reference options + 15 keyframe generations (10 shots, 5 retakes) on klein-4b, all logged in `runs.jsonl`.

## E4. Batch narration: can one TTS request replace ten?
- **Hypothesis:** if all 10 lines are sent in one request, separated by blank lines, with the style instruction "leave a long, clear pause of about two seconds between paragraphs", the pauses between lines will be clearly longer than the pauses inside lines, so the take can be cut at its 9 longest silences. That would turn 10 requests into 1 against a 10-requests/day free quota (F8).
- **Change:** `narration_defaults.batch = true`; model `gemini-3.8-flash-lite-tts`, voice `Sulafat`.
- **Result:** one request, 55.2 s take (`outputs/narration/batch__b9d8a446c3c4.wav`, 8.2 s latency). The splitter found 30 pauses of at least 0.25 s; the longest were only 1.22, 1.04, 0.80, 0.78, 0.78 ... 0.60 s. The model **did not leave two-second pauses** between lines, so gaps between lines were no longer than pauses between sentences inside a line (s02, s04, s06 each have two sentences). The cut was **rejected by the plausibility check**: piece 5 came out at 16.06 s where its text suggests ~4.10 s. The pipeline logged a `fallback` and generated the lines one by one (10 requests).
- **Decision:** keep batch mode (it is cheap to try and safe because of the check), but do not rely on it. The safety check earned its place: without it the film would have had narration lines on the wrong shots.
- **Next idea, if quota becomes critical:** put a short, distinct marker between lines (or one line per request only for lines with internal sentences).

## E5 (observation). Single-pass loudness normalisation undershoots
- **Measured** on `outputs/final/radio_cut.mp4` (EBU R128): **-15.6 LUFS** integrated, true peak **-0.8 dBFS**, against a target of -14 LUFS / -1 dBTP.
- **Cause:** FFmpeg's `loudnorm` in a single pass estimates as it goes; the brief recommends two passes for accuracy.
- **Decision:** acceptable for the radio cut (a prototype for listening tests). The final assembly (Phase 7) uses two-pass `loudnorm` and is measured again.
- **Phase 7 follow-up: two-pass did not fix it either. Every attempt was measured on the delivered MP4 (`stage: assemble` lines in `runs.jsonl`, 25 Nov 18:00-18:11 UTC):**

  | # | Mastering | LUFS | True peak | Verdict |
  |---|---|---|---|---|
  | 1 | two-pass `loudnorm` (`linear=true`) | -14.96 | -1.29 | loudness off by 1 LU |
  | 2 | C2PA noise removed (F11); voice compressor 2.5:1; gain + `alimiter` at 48 kHz | -14.14 | **-0.87** | the check flagged the peak |
  | 3 | same, limiter **4x oversampled** (192 kHz) | **-14.13** | **-1.87** | both on target |

  - **Why 1 missed:** `linear=true` only applies when the gain fits under the true-peak limit. The voice had ~20 dB between peak and loudness (partly the F11 noise), and -14 LUFS with peaks under -1.5 allows ~12.5 dB. So loudnorm silently switched to dynamic mode and landed 1 LU short.
  - **Why 2 missed:** `alimiter` limits samples. After +10 dB of gain, the peaks *between* samples rose 1.2 dB above its limit. Running it at 4x the sample rate lets it see them. This is the usual way a true-peak limiter is built.
  - **What made the difference:** an automatic check that measures the delivered file against the brief's numbers. It caught both misses, and nobody had to listen for them.
  - **Final chain:**
    1. Narration bus: `acompressor` 2.5:1 above -18 dBFS.
    2. Duck the music under it.
    3. Measure, then apply one gain to -14 LUFS.
    4. 4x-oversampled limiter at -2.0 dBFS.
    5. Measure again; if it missed by more than 0.2 LU, correct the gain and repeat (3 passes here).
    6. AAC, then measure the MP4.

## E8 (observation). Choosing the score: three seeds, same prompt, measured before listening
- **Setup:** ACE-Step 1.5 made one prompt (`storyboard.json` → `music.cues[0]`, 72 bpm, instrumental, 90 s) with seeds 11, 22 and 33, on a free Colab T4. Per the sidecars, the GPU time was 11.3 s, 8.7 s and 8.8 s. All three came in at -14.8 to -15.6 LUFS with peaks under -0.5 dBTP.
- **Measured** (FFmpeg `astats`, scratch script; the film is 83.1 s):

  | Seed | Level swing over 3 s windows | 1-4 kHz (speech band) vs full band | Where it ends |
  |---|---|---|---|
  | 11 | 52.3 dB | -22.7 dB | goes silent at ~79 s |
  | 22 | **9.4 dB** | -18.0 dB | plays to ~86 s, then fades |
  | 33 | 54.0 dB | -21.0 dB | goes silent at ~78 s |

- **Decision (provisional, by measurement; the owner can overrule it by ear):** `score-seed22`. Seeds 11 and 33 end before the film does, so the end card would sit in silence. Seed 22 is also the steadiest bed. It puts the most energy in the speech band, but the bed sits at -26 LUFS before mixing and is ducked under every line.
- **Result:** both films were rebuilt with it: -14.1 LUFS, -1.9 dBTP. The speech passages measure -13.7 dB RMS and the music-only gap after s09 -16.2 dB, so the music still rises between lines as designed.
- **Lesson:** the same prompt with different seeds gave different *structures* (where the piece ends), not just different textures. Measuring the ending took one script and would have been easy to miss by ear on a 90-second loop.

## E9. Ducking: how far under the voice does the score really sit?
- **Why:** in user test 2, two of three viewers said the music was too loud under the voice, in the first 20 s and at "Then came the fire" (DESIGN §5). E. said the same about the radio cut (§4). The film used the brief's suggested starting point (threshold 0.02, ratio 6, attack 300 ms, release 1500 ms) on a score levelled to -26 LUFS.
- **Hypothesis:** those settings keep the score at least 12 dB under the voice in every line, so the complaint is about a few loud moments in the score, not the duck itself.
- **Method:** the film's own audio graph (`radio.audio_graph`), rendered as two separate tracks, voice and ducked music. The RMS of each was measured over every narration line (0.2 s trimmed at each end), and the music level in the pauses between lines. One change per variant, the same score (`score-seed22`) and the same narration. Script: scratchpad `duck_exp.py`, 26 Nov.

  | Variant | Change | Voice minus music, median | Worst line | Worst in first 20 s | Music in pauses |
  |---|---|---|---|---|---|
  | A (as shipped) | 0.02 / 6 / 300 ms, bed -26 LUFS | 12.9 dB | **9.3 dB (s08)** | 12.6 dB | -27.5 dBFS |
  | B | threshold 0.01, ratio 10, attack 100 ms | **21.2 dB** | **17.3 dB** (s08) | 20.3 dB | -31.9 dBFS |
  | C | bed -29 LUFS only | 15.9 dB | 12.3 dB | 15.6 dB | -30.5 dBFS |
  | D | bed -29 LUFS + attack 100 ms | 17.7 dB | 14.1 dB | 17.1 dB | -31.1 dBFS |

- **Result:** the hypothesis was **wrong**. At the suggested settings the score sat only 9.3 dB under the voice in s08 and 9.8 dB in s05. The listeners were hearing a real level problem, not a loud passage. A 300 ms attack lets the start of every line through before the duck takes hold. A deeper, faster duck (B) gained about 8 dB under every line. Lowering the whole score (C) gained only 3 dB and also made the pauses quieter.
- **Decision:** B, in `storyboard.json` `mix.duck`. The score drops to about -32 dBFS in the pauses, against -27.5 before. That is still audible, and listeners wanted the voice to lead (D.: "the narration remains the main focus").
- **Lesson:** a suggested default is a starting point. The brief says "tune by ear"; measuring the two tracks separately showed *where* the ear was right, line by line.

## E10. What does real motion cost? Wan 2.2 on a free T4 vs a Ken Burns pan/zoom
- **Question:** the brief offers Ken Burns as the fallback and Wan 2.2 TI2V-5B as the real thing. How much more does motion cost per shot, measured here?
- **Hypothesis:** Wan costs at least 100x more compute per shot than Ken Burns, so it should be spent only where motion carries meaning (smoke, pouring, the door). That is why only s03, s07 and s10 were sent to Wan (PLAN §2.1).
- **Measured** (`runs.jsonl` `stage: shots`; the Wan sidecars in `out (4).zip`, ingested 26 Nov):

  | | Ken Burns (FFmpeg `zoompan`, local CPU) | Wan 2.2 TI2V-5B, 640 px, 30 steps (free Colab T4) |
  |---|---|---|
  | Time per shot | 6.0-10.7 s for a 6-9 s shot (12 renders) | **1313 s** of GPU per 5.04 s clip (denoise 827 s + decode 486 s), plus 355 s of text encoding once for all 3 and model loading |
  | Per second of footage | about 1 s of CPU | about 260 s of GPU |
  | Failure rate getting there | 0 | 6 failed Colab attempts before the 7th worked (FAILURES F12); 0 GPU hours from Kaggle in more than 15 h of queueing |
  | What viewers said | D. (test 2, all Ken Burns): images "still for… 6-9 seconds… feel a little static"; D. and K. lost interest in the slow, still middle | not yet shown to viewers |

- **Result:** about 130-200x more time per shot, so the hypothesis held. The real cost was not the GPU seconds but **getting a GPU at all**, plus six failed attempts to fit the model in 15 GB. A 5.04 s clip also has to fill a 6.5-7.5 s slot. The shot stage slows it down (at most `MAX_SLOWDOWN`) and holds the last frame (`pipeline/shots.py`). Shortening s07 from 8 to 6.5 s (user test 1) also reduced that stretch.
- **Decision:** Wan for the three shots where motion *is* the meaning (s03 smoke, s07 the pour, s10 the door), Ken Burns for the other seven. **Not measured:** whether viewers notice the difference. A blind A/B of the Ken Burns and Wan versions of s07 with 5 people would answer it (open).
