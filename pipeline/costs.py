"""python -m pipeline costs  -  (re)write COSTS.md from runs.jsonl.

Every number in the report is computed from runs.jsonl at the moment the command runs,
so it can be re-run whenever the log grows. The only numbers NOT from the log are the
list prices below, each with its source page and the date it was read. They turn the
logged units (tokens, image tiles, GPU seconds) into a "what this would have cost on a
paid plan" ESTIMATE. The money actually spent is whatever the log records as `usd`
inside an event's `cost` (nothing does: every provider here was used on a free tier).

Assumptions (also printed in the report):
  - a failed API request (status error) is not billed; a failed Kaggle/Colab job still
    used GPU time, so its logged GPU seconds are priced;
  - cache_hit events carry no provider; they are attributed to the provider/model of the
    event that produced the same input_hash.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

PRICES_CHECKED = "2026-11-26"
SOURCES = {
    "gemini": ("Gemini API pricing (Standard tier; ai.google.dev/gemini-api/docs/pricing redirects here)",
               "https://aistudio.google.com/docs/pricing"),
    "cloudflare": ("Cloudflare Workers AI pricing", "https://developers.cloudflare.com/workers-ai/platform/pricing/"),
    "gpu": ("getdeploying.com NVIDIA T4 price comparison (aggregator, not a provider page)",
            "https://getdeploying.com/reference/cloud-gpu/nvidia-t4"),
}
# USD per 1M tokens (input text, output). Gemini: the rates listed "through Dec 31, 2026";
# the page lists double these from Jan 1, 2027.
TOKEN_PRICES = {
    "gemini-3.8-flash-tts": (0.50, 9.00),
    "gemini-3.8-flash-lite-tts": (0.50, 6.00),
    "gemini-3.1-flash-tts-preview": (1.00, 20.00),
    "gemini-3.8-flash": (0.75, 3.75),
}
# Cloudflare: USD per 512x512 tile (input reference image tile, output tile).
TILE_PRICES = {"@cf/black-forest-labs/flux-2-klein-4b": (0.000059, 0.000287)}
NEURON_USD = 0.011 / 1000  # $0.011 per 1,000 neurons; free allocation 10,000 neurons/day
GPU_HOUR_USD = 0.42  # T4, Google Cloud on-demand "from" price per GPU-hour (aggregator)

STATUSES = ("ok", "error", "cache_hit", "fallback", "skipped")
STAGE_RANK = {s: i for i, s in enumerate(
    ("smoke", "refs", "narration", "keyframes", "clips", "shots", "music", "assemble"))}
PAID_PROVIDERS = ("gemini", "cloudflare", "kaggle")
MAINTENANCE_MODELS = ("repair-c2pa",)  # one-off fixes of existing files, not productions


# ---- reading -----------------------------------------------------------------------

def read_log(path: Path) -> tuple[list[dict[str, Any]], int, int]:
    """(events, lines in the file, lines that are not valid JSON objects)."""
    if not Path(path).exists():
        return [], 0, 0
    events, lines, bad = [], 0, 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            lines += 1
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                bad += 1
    return events, lines, bad


def attribute(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Copy of the events where every cache_hit gets the provider/model of the event that made
    the same input_hash. Returns (events, cache hits that could not be attributed)."""
    producer: dict[str, tuple[Any, Any]] = {}
    for e in events:
        if e.get("status") != "cache_hit" and e.get("input_hash") and e.get("provider"):
            producer.setdefault(e["input_hash"], (e.get("provider"), e.get("model")))
    out, unmatched = [], 0
    for e in events:
        e = dict(e)
        if e.get("status") == "cache_hit" and not e.get("provider"):
            if e.get("input_hash") in producer:
                e["provider"], e["model"] = producer[e["input_hash"]]
            else:
                unmatched += 1
        out.append(e)
    return out, unmatched


# ---- units and prices --------------------------------------------------------------

def _size(params: dict[str, Any]) -> tuple[int, int] | None:
    size = params.get("size")
    if isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) for v in size):
        return size[0], size[1]
    if isinstance(params.get("width"), int) and isinstance(params.get("height"), int):
        return params["width"], params["height"]
    return None


def tiles(width: int, height: int) -> int:
    return math.ceil(width / 512) * math.ceil(height / 512)


def estimate_usd(e: dict[str, Any]) -> float | None:
    """List-price equivalent of one event, or None when no price is known for it."""
    status, provider, model = e.get("status"), e.get("provider"), e.get("model")
    if status in ("cache_hit", "skipped") or provider in (None, "local"):
        return None
    if provider == "kaggle":
        if model == "kaggle-api":
            return None
        if isinstance(e.get("gpu_minutes"), (int, float)):
            return e["gpu_minutes"] / 60 * GPU_HOUR_USD
        return None
    if status != "ok":
        return 0.0 if status == "error" else None  # assumption: failed requests are not billed
    cost = e.get("cost") if isinstance(e.get("cost"), dict) else {}
    if model in TOKEN_PRICES and cost.get("unit") == "tokens":
        p_in, p_out = TOKEN_PRICES[model]
        return ((cost.get("input") or 0) * p_in + (cost.get("output") or 0) * p_out) / 1e6
    if cost.get("unit") == "neurons" and isinstance(cost.get("amount"), (int, float)):
        return cost["amount"] * NEURON_USD
    if model in TILE_PRICES:
        size = _size(e.get("params") or {})
        if size is None:
            return None
        p_in, p_out = TILE_PRICES[model]
        refs = (e.get("params") or {}).get("refs")
        return tiles(*size) * p_out + (len(refs) if isinstance(refs, list) else 0) * p_in
    return None


@dataclass
class Group:
    stage: str
    provider: str
    model: str
    counts: Counter = field(default_factory=Counter)
    latencies: list[int] = field(default_factory=list)  # every non-cache event that has one
    ok_latencies: list[int] = field(default_factory=list)
    units: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    spent: float = 0.0
    estimate: float = 0.0
    priced: int = 0
    unpriced: int = 0
    ok_estimates: list[float] = field(default_factory=list)
    produced: int = 0  # outside the smoke test: ok/fallback events that wrote an output

    def add(self, e: dict[str, Any]) -> None:
        status = e.get("status")
        self.counts[status] += 1
        if status == "cache_hit":
            return
        if (status in ("ok", "fallback") and e.get("output") and self.stage != "smoke"
                and self.model not in MAINTENANCE_MODELS):
            self.produced += 1
        lat = e.get("latency_ms")
        if isinstance(lat, (int, float)):
            self.latencies.append(int(lat))
            if status == "ok":
                self.ok_latencies.append(int(lat))
        cost = e.get("cost") if isinstance(e.get("cost"), dict) else {}
        if isinstance(cost.get("usd"), (int, float)):
            self.spent += cost["usd"]
        if cost.get("unit") == "tokens":
            self.units["input tokens"] += cost.get("input") or 0
            self.units["output tokens"] += cost.get("output") or 0
            if cost.get("audio_s") is not None:
                self.units["audio s"] += cost["audio_s"]
        if cost.get("unit") == "neurons" and isinstance(cost.get("amount"), (int, float)):
            self.units["neurons (logged)"] += cost["amount"]
        params = e.get("params") if isinstance(e.get("params"), dict) else {}
        if self.provider == "cloudflare" and status == "ok":
            self.units["images"] += 1
            size = _size(params)
            if size:
                self.units["output tiles"] += tiles(*size)
            if isinstance(params.get("refs"), list) and params["refs"]:
                self.units["ref-image tiles"] += len(params["refs"])
        if isinstance(e.get("gpu_minutes"), (int, float)):
            self.units["GPU s"] += e["gpu_minutes"] * 60
        if self.provider == "local" and status in ("ok", "fallback") and isinstance(lat, (int, float)):
            self.units["local CPU s"] += lat / 1000
        if self.provider == "local" and status in ("ok", "fallback"):
            self.units["outputs"] += 1
        usd = estimate_usd(e)
        if usd is None:
            # a fallback/skipped marker is not a call; only real calls without a price count here
            if self.provider in PAID_PROVIDERS and self.model != "kaggle-api" and status in ("ok", "error"):
                self.unpriced += 1
        else:
            self.priced += 1
            self.estimate += usd
            if status == "ok":
                self.ok_estimates.append(usd)


def group_events(events: Iterable[dict[str, Any]]) -> list[Group]:
    groups: dict[tuple[str, str, str], Group] = {}
    for e in events:
        key = (str(e.get("stage")), str(e.get("provider") or "(unknown)"), str(e.get("model") or "(none)"))
        groups.setdefault(key, Group(*key)).add(e)
    return sorted(groups.values(), key=lambda g: (STAGE_RANK.get(g.stage, 99), g.stage, g.provider, g.model))


# ---- formatting --------------------------------------------------------------------

def _usd(x: float) -> str:
    if x == 0:
        return "$0"
    if x < 0.0001:
        return "<$0.0001"
    return f"${x:.4f}"


def _secs(ms: float) -> str:
    s = ms / 1000
    if s < 1:
        return f"{ms:.0f} ms"
    if s >= 120:
        return f"{s / 60:.1f} min"
    return f"{s:.1f} s"


def _units(g: Group) -> str:
    def fmt(k: str, v: float) -> str:
        return f"{v:,.1f} {k}" if k.endswith(" s") else f"{v:,.0f} {k}"
    return "; ".join(fmt(k, v) for k, v in g.units.items() if v) or "-"


def _estimate_cell(g: Group) -> str:
    if g.provider == "local":
        return "n/a (local)"
    if g.priced == 0:
        return "no price" if g.unpriced or g.model == "kaggle-api" else "-"
    cell = _usd(g.estimate)
    return cell + (f" ({g.unpriced} unpriced)" if g.unpriced else "")


def _short_model(model: str) -> str:
    return model.removeprefix("@cf/black-forest-labs/")


def error_class(text: str | None) -> str:
    m = re.match(r"^([A-Za-z]+Error)\b", text or "")
    return m.group(1) if m else "other"


@dataclass
class PlanRow:
    stage: str
    cached: int
    would_run: int
    blocked: int
    where: str  # "provider API", "local FFmpeg", "Kaggle/Colab notebook"


def build_report(events: list[dict[str, Any]], *, line_count: int, bad_lines: int,
                 plan: list[PlanRow] | None = None, now: datetime | None = None,
                 log_name: str = "runs.jsonl") -> str:
    now = now or datetime.now(timezone.utc)
    events, unmatched = attribute(events)
    groups = group_events(events)
    ts = sorted(e["ts"] for e in events if isinstance(e.get("ts"), str))
    runs = {e.get("run_id") for e in events if e.get("run_id")}
    total_est = sum(g.estimate for g in groups)
    spent = sum(g.spent for g in groups)
    by_status = Counter(e.get("status") for e in events)

    out: list[str] = []
    w = out.append
    w("# COSTS: what the film cost, from the logs")
    w("")
    w(f"Generated {now.isoformat(timespec='seconds')} by `python -m pipeline costs` from `{log_name}` "
      f"({line_count} lines, {len(events)} events, {bad_lines} unreadable; {len(runs)} runs"
      + (f", {ts[0][:16]}Z to {ts[-1][:16]}Z" if ts else "") + "). "
      "Re-run the command to refresh it; every number below except the list prices is computed from the log.")
    w("")
    w("## Headline")
    w("")
    w(f"- **Money actually spent: {_usd(spent)}.** No event in the log records a charge (`cost.usd`); "
      "every provider was used on its free tier (Gemini free tier, Cloudflare's daily free neurons, "
      "free Kaggle/Colab GPUs).")
    w(f"- **List-price equivalent (estimate): {_usd(total_est)}**: what the logged successful calls and "
      "GPU seconds would have cost at the published paid prices (sources and dates below). "
      "Prices checked " + PRICES_CHECKED + ".")
    provider_ms: dict[str, int] = defaultdict(int)
    for g in groups:
        if g.provider not in ("local", "(unknown)"):
            provider_ms[g.provider] += sum(g.latencies)
    local_ms = sum(sum(g.latencies) for g in groups if g.provider == "local")
    w(f"- **Wall-clock inside provider calls: {_secs(sum(provider_ms.values()))}** ("
      + ", ".join(f"{p} {_secs(ms)}" for p, ms in sorted(provider_ms.items())) + "), including failed "
      "attempts. For ingested notebook jobs this is the job time the notebook measured, not the whole "
      "session (see the data gaps). "
      f"Local FFmpeg work: {_secs(local_ms)}.")
    w(f"- Events by status: " + ", ".join(f"{s} {by_status.get(s, 0)}" for s in STATUSES) + ".")
    w("")

    w("## Per stage and model")
    w("")
    w("Latency is over every non-cache event that logged one (errors included); the median is over the same "
      "events. Units are summed over successful calls (GPU seconds over every job, failed ones too).")
    w("")
    w("| Stage | Provider | Model | ok | error | cache_hit | fallback | Latency total | Latency median "
      "| Units | Spent | List-price est. |")
    w("|---|---|---|--:|--:|--:|--:|--:|--:|---|--:|--:|")
    for g in groups:
        med = _secs(statistics.median(g.latencies)) if g.latencies else "-"
        tot = _secs(sum(g.latencies)) if g.latencies else "-"
        w(f"| {g.stage} | {g.provider} | {_short_model(g.model)} | {g.counts['ok']} | {g.counts['error']} | "
          f"{g.counts['cache_hit']} | {g.counts['fallback']} | {tot} | {med} | {_units(g)} | {_usd(g.spent)} | "
          f"{_estimate_cell(g)} |")
    w("")

    w("## What the cache saved")
    w("")
    hits = by_status.get("cache_hit", 0)
    made = sum(g.produced for g in groups)
    ratio = hits / (hits + made) if hits + made else 0.0
    w(f"Outside the smoke test, {hits} jobs were served from the cache and {made} outputs were produced "
      "(ok or fallback events that wrote an output; the one-off `repair-c2pa` fixes and the batch-rejected "
      f"marker are not counted): a cache-hit ratio of **{ratio:.0%}**. Saved time is each cache hit times "
      "the median latency of that model's successful calls; saved money is each hit times the mean "
      "list-price estimate of those calls.")
    w("")
    w("| Stage | Provider | Model | cache hits | produced | est. time saved | est. list price saved |")
    w("|---|---|---|--:|--:|--:|--:|")
    saved_ms = saved_usd = 0.0
    for g in groups:
        n = g.counts["cache_hit"]
        if not n:
            continue
        t = n * statistics.median(g.ok_latencies) if g.ok_latencies else None
        u = n * statistics.mean(g.ok_estimates) if g.ok_estimates else None
        saved_ms += t or 0
        saved_usd += u or 0
        w(f"| {g.stage} | {g.provider} | {_short_model(g.model)} | {n} | {g.produced} | "
          f"{_secs(t) if t is not None else '-'} | {_usd(u) if u is not None else ('n/a (local)' if g.provider == 'local' else '-')} |")
    w(f"| **total** | | | **{hits}** | | **{_secs(saved_ms)}** | **{_usd(saved_usd)}** |")
    w("")
    w("The bigger saving is quota, not money: Gemini's free tier allowed about 10 TTS requests per model "
      "per day (FAILURES F8), so every cached narration line is a request that did not count against it.")
    w("")

    w("## What a re-run costs")
    w("")
    if plan is None:
        w("Not computed (no storyboard/manifest given).")
    else:
        calls = sum(r.would_run for r in plan if r.where == "provider API")
        gpu = sum(r.would_run for r in plan if r.where.startswith("Kaggle"))
        w(f"`python -m pipeline all` right now: **{calls} provider call(s)**"
          + (f"; {gpu} GPU job(s) still to make in a notebook (not called by `all`; the film uses its "
             "fallback meanwhile)" if gpu else "")
          + ". With everything cached a re-run makes 0 provider calls and costs $0; only the local FFmpeg "
          "stages re-render, and only if one of their inputs changed. Snapshot at generation time:")
        w("")
        w("| Stage | Runs on | cached | would run | blocked |")
        w("|---|---|--:|--:|--:|")
        for r in plan:
            w(f"| {r.stage} | {r.where} | {r.cached} | {r.would_run} | {r.blocked} |")
    w("")

    w("## Errors by kind")
    w("")
    errs = Counter((e.get("provider") or "(unknown)", error_class(e.get("error")))
                   for e in events if e.get("status") == "error")
    if errs:
        w("| Provider | Error class | count |")
        w("|---|---|--:|")
        for (p, c), n in sorted(errs.items()):
            w(f"| {p} | {c} | {n} |")
        w("")
        w("Failed API requests are assumed unbilled. The causes and fixes are in FAILURES.md.")
    else:
        w("No errors logged.")
    w("")

    w("## Frontier comparison")
    w("")
    w("Not done. The frontier image, video and music models (Omni Flash, Nano Banana, Lyria 3.5) need paid "
      "API billing, which this project did not have. Chat subscriptions do not give the pipeline API access, "
      "so no frontier call could be made, logged or compared. Every model in the film is free-tier or open-weight.")
    w("")

    w("## Prices used for the estimate")
    w("")
    w(f"All checked {PRICES_CHECKED}. These are list-price **equivalents** for a paid plan, not money spent.")
    w("")
    w("| What | Price | Source |")
    w("|---|---|---|")
    src = {k: f"[{t}]({u})" for k, (t, u) in SOURCES.items()}
    for model, (p_in, p_out) in TOKEN_PRICES.items():
        kind = "audio " if "tts" in model else ""
        w(f"| {model} | ${p_in:.2f} / 1M input tokens, ${p_out:.2f} / 1M {kind}output tokens "
          f"(paid Standard tier; the page lists double from 1 Jan 2027) | {src['gemini']} |")
    for model, (p_in, p_out) in TILE_PRICES.items():
        w(f"| {_short_model(model)} | ${p_out:.6f} per output 512x512 tile, ${p_in:.6f} per input 512x512 tile "
          f"(each reference image is uploaded at most 512x512, so 1 tile) | {src['cloudflare']} |")
    w(f"| Workers AI neurons (flux-1-schnell, logged as neurons) | $0.011 per 1,000 neurons; free: 10,000 "
      f"neurons/day | {src['cloudflare']} |")
    w(f"| GPU time (Kaggle / Colab T4, free) | ${GPU_HOUR_USD:.2f} per T4 GPU-hour (Google Cloud on-demand "
      f"\"from\" price, as listed by an aggregator; the provider page could not be read) | {src['gpu']} |")
    w("| Kaggle API (smoke test), local FFmpeg | no price: free API / own machine | - |")
    no_price = sorted({_short_model(g.model) for g in groups if g.provider in ("gemini", "cloudflare")
                       and g.model not in TOKEN_PRICES and g.model not in TILE_PRICES
                       and not g.units.get("neurons (logged)")})
    if no_price:
        w(f"| {', '.join(no_price)} | no price in this report (their failed requests count as $0; any "
          "successful call is shown as unpriced) | - |")
    w("")

    w("## Data gaps in the log")
    w("")
    for gap in data_gaps(events, unmatched):
        w(f"- {gap}")
    w("")
    return "\n".join(out)


def data_gaps(events: list[dict[str, Any]], unmatched_hits: int) -> list[str]:
    gaps: list[str] = []
    no_lat = Counter((e.get("stage"), e.get("provider"), e.get("model"), e.get("status")) for e in events
                     if e.get("status") in ("ok", "error", "fallback") and e.get("latency_ms") is None)
    for (stage, provider, model, status), n in sorted(no_lat.items(), key=str):
        gaps.append(f"{n} `{status}` event(s) in `{stage}` ({provider}/{model}) have no `latency_ms`.")
    cf = [e for e in events if e.get("provider") == "cloudflare" and e.get("status") == "ok"]
    cf_no_cost = [e for e in cf if not (isinstance(e.get("cost"), dict)
                                         and isinstance(e["cost"].get("amount"), (int, float)))]
    if cf_no_cost:
        gaps.append(f"{len(cf_no_cost)} of {len(cf)} successful Cloudflare calls log no neuron count "
                    "(`cost` is null, or `amount` is null for klein); their estimate is computed from the "
                    "image size and reference count in `params`, not from a provider-reported figure.")
    gpu_jobs = [e for e in events if e.get("provider") == "kaggle" and e.get("model") != "kaggle-api"]
    no_gpu = [e for e in gpu_jobs if e.get("gpu_minutes") is None]
    if no_gpu:
        gaps.append(f"{len(no_gpu)} notebook event(s) have no `gpu_minutes`, so they are not priced. They were "
                    "not written by `ingest` (no sidecar); they record a whole failed notebook run, and their "
                    "`latency_ms` is that run's length.")
    if gpu_jobs:
        gaps.append("GPU seconds come from each job's sidecar and cover only that job's generation. Session "
                    "overhead (weight download, text encoding, preflight, crashed sessions that wrote no "
                    "sidecar) is not in the log, so real GPU time was higher than shown.")
    tts = [e for e in events if e.get("provider") == "gemini" and e.get("status") == "ok"]
    if tts:
        gaps.append("Gemini events log tokens (the billed unit) and audio seconds, not characters. Text "
                    "models' thinking tokens are not logged separately.")
    if unmatched_hits:
        gaps.append(f"{unmatched_hits} cache_hit event(s) could not be matched to the event that produced "
                    "them (no producing event with the same input_hash); they are shown as `(unknown)`.")
    no_attempt = [e for e in events if e.get("status") in ("ok", "error") and e.get("attempt") is None]
    if no_attempt:
        gaps.append(f"{len(no_attempt)} ok/error event(s) have no `attempt` (local renders and notebook "
                    "ingests are not retried by `logged_call`).")
    if not gaps:
        gaps.append("none found.")
    return gaps


# ---- the command ---------------------------------------------------------------------

def rerun_plan(ctx: Any, stages: dict[str, Any], fresh: Callable[[Any, str, Any], bool]) -> list[PlanRow]:
    """What `python -m pipeline all` would do now (same freshness test as --dry-run), plus the
    Wan clips that are made in a notebook. Reads the manifest; changes nothing."""
    from . import shots

    rows = []
    for name, module in stages.items():
        jobs = module.jobs(ctx.sb, ctx.manifest)
        blocked = [j for j in jobs if j.blocked]
        ready = [j for j in jobs if not j.blocked]
        cached = [j for j in ready if fresh(ctx, name, j)]
        where = ("Kaggle/Colab notebook" if name == "music" else
                 "local FFmpeg" if getattr(module, "LOCAL", False) else "provider API")
        rows.append(PlanRow(name, len(cached), len(ready) - len(cached), len(blocked), where))
        if name == "shots":
            clips = shots.clip_jobs(ctx.sb, ctx.manifest)
            done = [j for j in clips if not j.blocked and ctx.manifest.is_fresh(j)]
            rows.append(PlanRow("clips (Wan)", len(done), len([j for j in clips if not j.blocked]) - len(done),
                                len([j for j in clips if j.blocked]), "Kaggle/Colab notebook"))
    return rows


def write(ctx: Any, stages: dict[str, Any] | None = None,
          fresh: Callable[[Any, str, Any], bool] | None = None) -> Path:
    events, lines, bad = read_log(ctx.paths.runs_log)
    plan = rerun_plan(ctx, stages, fresh) if stages is not None and fresh is not None else None
    text = build_report(events, line_count=lines, bad_lines=bad, plan=plan)
    out = ctx.paths.root / "COSTS.md"
    tmp = out.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(out)
    print(f"[costs] {ctx.paths.rel(out)} from {lines} log lines ({len(events)} events)")
    return out
