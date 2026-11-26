# COSTS: what the film cost, from the logs

Generated 2026-11-26T09:05:54+00:00 by `python -m pipeline costs` from `runs.jsonl` (255 lines, 255 events, 0 unreadable; 24 runs, 2026-11-25T09:07Z to 2026-11-26T08:50Z). Re-run the command to refresh it; every number below except the list prices is computed from the log.

## Headline

- **Money actually spent: $0.** No event in the log records a charge (`cost.usd`); every provider was used on its free tier (Gemini free tier, Cloudflare's daily free neurons, free Kaggle/Colab GPUs).
- **List-price equivalent (estimate): $0.1065**: what the logged successful calls and GPU seconds would have cost at the published paid prices (sources and dates below). Prices checked 2026-11-26.
- **Wall-clock inside provider calls: 18.9 min** (cloudflare 4.5 min, gemini 6.1 min, kaggle 8.3 min), including failed attempts. For ingested notebook jobs this is the job time the notebook measured, not the whole session (see the data gaps). Local FFmpeg work: 12.1 min.
- Events by status: ok 97, error 52, cache_hit 98, fallback 8, skipped 0.

## Per stage and model

Latency is over every non-cache event that logged one (errors included); the median is over the same events. Units are summed over successful calls (GPU seconds over every job, failed ones too).

| Stage | Provider | Model | ok | error | cache_hit | fallback | Latency total | Latency median | Units | Spent | List-price est. |
|---|---|---|--:|--:|--:|--:|--:|--:|---|--:|--:|
| smoke | cloudflare | flux-1-schnell | 1 | 10 | 0 | 0 | 2.8 s | 40 ms | 58 neurons (logged); 1 images | $0 | $0.0006 |
| smoke | cloudflare | flux-2-klein-4b | 2 | 0 | 0 | 0 | 16.1 s | 8.1 s | 2 images; 12 output tiles | $0 | $0.0034 |
| smoke | cloudflare | flux-2-klein-9b | 0 | 1 | 0 | 0 | 43 ms | 43 ms | - | $0 | $0 |
| smoke | gemini | gemini-3.1-flash-tts-preview | 0 | 2 | 0 | 0 | 213 ms | 106 ms | - | $0 | $0 |
| smoke | gemini | gemini-3.7-flash | 0 | 9 | 0 | 0 | 17.0 s | 1.5 s | - | $0 | $0 |
| smoke | gemini | gemini-3.8-flash | 1 | 13 | 0 | 0 | 4.3 min | 2.3 s | 67 input tokens; 18 output tokens | $0 | $0.0001 |
| smoke | gemini | gemini-3.8-flash-tts | 13 | 4 | 0 | 0 | 46.5 s | 3.0 s | 247 input tokens; 2,460 output tokens; 100.4 audio s | $0 | $0.0223 |
| smoke | gemini | gemini-omni-flash-preview | 0 | 2 | 0 | 0 | 332 ms | 166 ms | - | $0 | $0 |
| smoke | kaggle | kaggle-api | 6 | 0 | 0 | 0 | 6.6 s | 1.1 s | - | $0 | no price |
| refs | cloudflare | flux-2-klein-4b | 12 | 0 | 0 | 0 | 105.3 s | 8.3 s | 12 images; 48 output tiles | $0 | $0.0138 |
| narration | gemini | gemini-3.8-flash-lite-tts | 11 | 3 | 30 | 1 | 35.3 s | 2.5 s | 536 input tokens; 2,991 output tokens; 121.3 audio s | $0 | $0.0182 |
| narration | gemini | gemini-3.8-flash-tts | 1 | 3 | 0 | 0 | 5.6 s | 374 ms | 34 input tokens; 232 output tokens; 9.4 audio s | $0 | $0.0021 |
| narration | local | repair-c2pa | 10 | 0 | 0 | 0 | - | - | 10 outputs | $0 | n/a (local) |
| keyframes | cloudflare | flux-2-klein-4b | 16 | 0 | 49 | 0 | 2.4 min | 8.9 s | 16 images; 144 output tiles; 14 ref-image tiles | $0 | $0.0422 |
| clips | kaggle | Wan-AI/Wan2.2-TI2V-5B-Diffusers | 0 | 4 | 0 | 0 | 7.0 min | 1.1 s | 3.6 GPU s | $0 | $0.0004 (1 unpriced) |
| shots | local | ffmpeg-zoompan | 13 | 0 | 17 | 7 | 2.8 min | 8.8 s | 169.2 local CPU s; 20 outputs | $0 | n/a (local) |
| music | kaggle | ACE-Step/Ace-Step1.5 | 3 | 1 | 0 | 0 | 76.4 s | 10.1 s | 28.8 GPU s | $0 | $0.0034 (1 unpriced) |
| assemble | local | ffmpeg | 8 | 0 | 2 | 0 | 9.3 min | 68.3 s | 557.8 local CPU s; 8 outputs | $0 | n/a (local) |

## What the cache saved

Outside the smoke test, 98 jobs were served from the cache and 71 outputs were produced (ok or fallback events that wrote an output; the one-off `repair-c2pa` fixes and the batch-rejected marker are not counted): a cache-hit ratio of **58%**. Saved time is each cache hit times the median latency of that model's successful calls; saved money is each hit times the mean list-price estimate of those calls.

| Stage | Provider | Model | cache hits | produced | est. time saved | est. list price saved |
|---|---|---|--:|--:|--:|--:|
| narration | gemini | gemini-3.8-flash-lite-tts | 30 | 11 | 75.0 s | $0.0497 |
| keyframes | cloudflare | flux-2-klein-4b | 49 | 16 | 7.2 min | $0.1291 |
| shots | local | ffmpeg-zoompan | 17 | 20 | 2.5 min | n/a (local) |
| assemble | local | ffmpeg | 2 | 8 | 2.3 min | n/a (local) |
| **total** | | | **98** | | **13.3 min** | **$0.1788** |

The bigger saving is quota, not money: Gemini's free tier allowed about 10 TTS requests per model per day (FAILURES F8), so every cached narration line is a request that did not count against it.

## What a re-run costs

`python -m pipeline all` right now: **0 provider call(s)**; 3 GPU job(s) still to make in a notebook (not called by `all`; the film uses its fallback meanwhile). With everything cached a re-run makes 0 provider calls and costs $0; only the local FFmpeg stages re-render, and only if one of their inputs changed. Snapshot at generation time:

| Stage | Runs on | cached | would run | blocked |
|---|---|--:|--:|--:|
| narration | provider API | 10 | 0 | 0 |
| keyframes | provider API | 10 | 0 | 0 |
| shots | local FFmpeg | 10 | 0 | 0 |
| clips (Wan) | Kaggle/Colab notebook | 0 | 3 | 0 |
| music | Kaggle/Colab notebook | 3 | 0 | 0 |
| assemble | local FFmpeg | 2 | 0 | 0 |

## Errors by kind

| Provider | Error class | count |
|---|---|--:|
| cloudflare | BadInputError | 11 |
| gemini | BadInputError | 3 |
| gemini | QuotaError | 15 |
| gemini | TransientError | 18 |
| kaggle | OutOfMemoryError | 3 |
| kaggle | other | 2 |

Failed API requests are assumed unbilled. The causes and fixes are in FAILURES.md.

## Prices used for the estimate

All checked 2026-11-26. These are list-price **equivalents** for a paid plan, not money spent.

| What | Price | Source |
|---|---|---|
| gemini-3.8-flash-tts | $0.50 / 1M input tokens, $9.00 / 1M audio output tokens (paid Standard tier; the page lists double from 1 Jan 2027) | [Gemini API pricing (Standard tier; ai.google.dev/gemini-api/docs/pricing redirects here)](https://aistudio.google.com/docs/pricing) |
| gemini-3.8-flash-lite-tts | $0.50 / 1M input tokens, $6.00 / 1M audio output tokens (paid Standard tier; the page lists double from 1 Jan 2027) | [Gemini API pricing (Standard tier; ai.google.dev/gemini-api/docs/pricing redirects here)](https://aistudio.google.com/docs/pricing) |
| gemini-3.1-flash-tts-preview | $1.00 / 1M input tokens, $20.00 / 1M audio output tokens (paid Standard tier; the page lists double from 1 Jan 2027) | [Gemini API pricing (Standard tier; ai.google.dev/gemini-api/docs/pricing redirects here)](https://aistudio.google.com/docs/pricing) |
| gemini-3.8-flash | $0.75 / 1M input tokens, $3.75 / 1M output tokens (paid Standard tier; the page lists double from 1 Jan 2027) | [Gemini API pricing (Standard tier; ai.google.dev/gemini-api/docs/pricing redirects here)](https://aistudio.google.com/docs/pricing) |
| flux-2-klein-4b | $0.000287 per output 512x512 tile, $0.000059 per input 512x512 tile (each reference image is uploaded at most 512x512, so 1 tile) | [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) |
| Workers AI neurons (flux-1-schnell, logged as neurons) | $0.011 per 1,000 neurons; free: 10,000 neurons/day | [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) |
| GPU time (Kaggle / Colab T4, free) | $0.42 per T4 GPU-hour (Google Cloud on-demand "from" price, as listed by an aggregator; the provider page could not be read) | [getdeploying.com NVIDIA T4 price comparison (aggregator, not a provider page)](https://getdeploying.com/reference/cloud-gpu/nvidia-t4) |
| Kaggle API (smoke test), local FFmpeg | no price: free API / own machine | - |
| flux-2-klein-9b, gemini-3.7-flash, gemini-omni-flash-preview | no price in this report (their failed requests count as $0; any successful call is shown as unpriced) | - |

## Data gaps in the log

- 1 `fallback` event(s) in `narration` (gemini/gemini-3.8-flash-lite-tts) have no `latency_ms`.
- 10 `ok` event(s) in `narration` (local/repair-c2pa) have no `latency_ms`.
- 30 of 31 successful Cloudflare calls log no neuron count (`cost` is null, or `amount` is null for klein); their estimate is computed from the image size and reference count in `params`, not from a provider-reported figure.
- 2 notebook event(s) have no `gpu_minutes`, so they are not priced. They were not written by `ingest` (no sidecar); they record a whole failed notebook run, and their `latency_ms` is that run's length.
- GPU seconds come from each job's sidecar and cover only that job's generation. Session overhead (weight download, text encoding, preflight, crashed sessions that wrote no sidecar) is not in the log, so real GPU time was higher than shown.
- Gemini events log tokens (the billed unit) and audio seconds, not characters. Text models' thinking tokens are not logged separately.
- 37 ok/error event(s) have no `attempt` (local renders and notebook ingests are not retried by `logged_call`).
