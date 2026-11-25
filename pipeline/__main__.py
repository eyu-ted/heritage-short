"""Command line: python -m pipeline <command> [options]

  validate                 check storyboard.json against the schema and semantic rules
  smoke                    call every provider once; record what really works (Phase 2)
  all                      run every stage in order (what `make film` calls)
  narration | keyframes | shots | music | assemble
                           run one stage
  refs                     reference sheet: options per reference; --pick jebena=2 approves one
  radio                    build the radio cut (narration + placeholder music on black)
  animatic                 the radio cut with the shots as picture (vertical 9:16)

Options:
  --dry-run       show what would run (cached / would run / blocked); no API calls
  --shot s07      limit shot-based stages to one shot (repeatable)
  --force         ignore the cache and regenerate
  --offline       never call a provider; use the cache or fail clearly

Exit codes: 0 ok, 1 invalid storyboard/usage, 2 not ready (upstream missing),
            3 provider failure (quota, outage, bad input), 4 FFmpeg failure.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import ModuleType

from . import assemble, keyframes, music, narration, shots
from .cache import Manifest
from .config import STAGE_ORDER, MissingSecretError, get_paths, load_env
from .context import Context
from .ffmpeg import FFmpegError
from .jobs import Job, NotReadyError
from .retry import StageError
from .runlog import log_event
from .storyboard import StoryboardError, check_ready, load, planned_duration

STAGES: dict[str, ModuleType] = {
    "narration": narration,
    "keyframes": keyframes,
    "shots": shots,
    "music": music,
    "assemble": assemble,
}
SHOT_STAGES = {"narration", "keyframes", "shots"}

EXIT_OK, EXIT_INVALID, EXIT_NOT_READY, EXIT_PROVIDER, EXIT_FFMPEG = 0, 1, 2, 3, 4


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m pipeline", description="Heritage Short pipeline")
    p.add_argument("command", choices=["validate", "smoke", "refs", "radio", "animatic", "all", *STAGE_ORDER])
    p.add_argument("--options", type=int, default=4, help="refs: options per reference (default 4)")
    p.add_argument("--pick", default=None, help="refs: approve an option, e.g. jebena=2")
    p.add_argument("--storyboard", type=Path, default=None, help="path to storyboard.json")
    p.add_argument("--shot", action="append", default=[], help="only this shot id (repeatable)")
    p.add_argument("--force", action="store_true", help="ignore cache, regenerate")
    p.add_argument("--dry-run", action="store_true", help="show the plan, call nothing")
    p.add_argument("--offline", action="store_true", help="no provider calls")
    return p


def _fresh(ctx: Context, stage: str, job: Job) -> bool:
    """A stage may refine freshness (shots: a Ken Burns fallback goes stale on its own inputs)."""
    custom = getattr(STAGES.get(stage), "is_fresh", None)
    return custom(ctx, job) if custom else ctx.manifest.is_fresh(job)


def _status(ctx: Context, stage: str, job: Job) -> str:
    if job.blocked:
        return f"blocked: {job.blocked}"
    if not ctx.force and _fresh(ctx, stage, job):
        return "cached"
    return "would run"


def _select(stage: str, jobs: list[Job], shot_ids: tuple[str, ...]) -> list[Job]:
    if shot_ids and stage in SHOT_STAGES:
        return [j for j in jobs if j.key in shot_ids]
    return jobs


def _print_plan(ctx: Context, stages: list[str]) -> None:
    counts = {"cached": 0, "would run": 0, "blocked": 0}
    print(f"{'stage':<10} {'key':<14} {'hash':<13} status")
    print("-" * 72)
    for stage in stages:
        for job in _select(stage, STAGES[stage].jobs(ctx.sb, ctx.manifest), ctx.shot_ids):
            status = _status(ctx, stage, job)
            counts["blocked" if status.startswith("blocked") else status] += 1
            print(f"{stage:<10} {job.key:<14} {job.hash:<13} {status}")
    print("-" * 72)
    print(f"cached: {counts['cached']}   would run: {counts['would run']}   blocked: {counts['blocked']}")


def _run_stage(ctx: Context, stage: str) -> None:
    """Run every job that is ready; then, if any were blocked, stop the pipeline here
    (later stages depend on them) and say why."""
    module = STAGES[stage]
    jobs = _select(stage, module.jobs(ctx.sb, ctx.manifest), ctx.shot_ids)
    blocked = [j for j in jobs if j.blocked]
    selected = [j for j in jobs if not j.blocked]

    todo = []
    for job in selected:
        if not ctx.force and _fresh(ctx, stage, job):
            entry = ctx.manifest.entry(stage, job.key)
            log_event(ctx.paths.runs_log, stage=stage, shot_id=job.key, model=job.inputs.get("model"),
                      input_hash=job.hash, output=entry["path"], status="cache_hit")
        else:
            todo.append(job)
    print(f"[{stage}] {len(selected) - len(todo)} cached, {len(todo)} to generate, {len(blocked)} blocked")
    if todo and ctx.offline:
        raise NotReadyError(f"{stage}: --offline but {len(todo)} job(s) are not cached: "
                            f"{[j.key for j in todo]}")
    module.run(ctx, todo)
    if blocked:
        raise NotReadyError(f"{stage}: {len(blocked)} job(s) blocked, e.g. {blocked[0].key}: {blocked[0].blocked}")


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = get_paths(root)

    try:
        sb = load(paths, args.storyboard)
    except StoryboardError as err:
        print(err, file=sys.stderr)
        return EXIT_INVALID

    known = {s["id"] for s in sb["shots"]}
    unknown = [s for s in args.shot if s not in known]
    if unknown:
        print(f"unknown shot id(s): {unknown}", file=sys.stderr)
        return EXIT_INVALID

    ctx = Context(paths=paths, sb=sb, manifest=Manifest(paths), force=args.force,
                  offline=args.offline, shot_ids=tuple(args.shot))

    if args.command == "validate":
        print(f"OK: storyboard '{sb['project']['title']}' is valid")
        print(f"  shots: {len(sb['shots'])}   planned duration: {planned_duration(sb):.1f}s")
        for stage in STAGE_ORDER:
            for problem in check_ready(sb, stage):
                print(f"  not ready for {stage}: {problem}")
        return EXIT_OK

    stages = list(STAGE_ORDER) if args.command == "all" else (
        [args.command] if args.command in STAGES else [])
    if args.dry_run:
        _print_plan(ctx, stages)
        return EXIT_OK

    load_env(paths)
    try:
        if args.command == "smoke":
            from . import smoke

            return smoke.run(paths, sb)
        if args.command in ("radio", "animatic"):
            from . import radio

            radio.build(ctx, picture=args.command == "animatic")
            return EXIT_OK
        if args.command == "refs":
            from . import refs

            if args.pick:
                print(f"[refs] approved {args.pick} -> {refs.pick(ctx, args.pick)}")
                return EXIT_OK
            ref_jobs = refs.jobs(ctx.sb, ctx.manifest, options=args.options)
            todo = [j for j in ref_jobs if args.force or not ctx.manifest.is_fresh(j)]
            print(f"[refs] {len(ref_jobs) - len(todo)} cached, {len(todo)} to generate")
            refs.run(ctx, todo)
            return EXIT_OK
        for stage in stages:
            _run_stage(ctx, stage)
    except NotImplementedError as err:
        print(f"not available yet: {err}", file=sys.stderr)
        return EXIT_NOT_READY
    except NotReadyError as err:
        print(f"not ready: {err}", file=sys.stderr)
        return EXIT_NOT_READY
    except MissingSecretError as err:
        print(f"missing secret: {err}", file=sys.stderr)
        return EXIT_PROVIDER
    except StageError as err:
        print(f"provider failure ({type(err).__name__}): {err}\n"
              "Finished work is cached; rerun the same command to continue.", file=sys.stderr)
        return EXIT_PROVIDER
    except FFmpegError as err:
        print(f"FFmpeg failure: {err}", file=sys.stderr)
        return EXIT_FFMPEG
    except ValueError as err:  # e.g. a bad --pick
        print(f"error: {err}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
