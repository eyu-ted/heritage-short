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
