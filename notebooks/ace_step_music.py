# %% [markdown]
# # Buna: ACE-Step 1.5 score candidates (Kaggle)
#
# Do not edit the jobs by hand. `python -m pipeline export music` builds this notebook from
# `notebooks/ace_step_music.py` and writes the jobs into the `JOBS` cell: caption, bpm,
# duration, seed, model variant and hash.
#
# **Run it:** Kaggle → Create → Import Notebook → this file. Settings: Accelerator **GPU T4 x2**
# (any 16 GB GPU works), Internet **on**. Then **Save Version → Save & Run All (Commit)**.
#
# **Bring the music home:** download `out/` from the version's Output, then run
# `python -m pipeline ingest music --from <the download>`.
#
# How it runs ACE-Step:
# - **Pinned to a tagged release** (`repo_tag` in the jobs), installed with pip.
# - **Kaggle's own PyTorch is kept** (the repo pins a newer one, used only if Kaggle's fails).
# - **The 5 Hz language model is never loaded** (`thinking=False`, CoT off), so bpm, key and
#   length are exactly the storyboard's.
#
# Generation runs in a **separate Python process**. If it fails on startup because of a missing
# package or an old PyTorch, the notebook repairs that once and tries again.

# %%
JOBS = None  # filled in by `python -m pipeline export music`

# %%
import glob, json, os, re, subprocess, sys, time

if JOBS is None:
    hits = glob.glob("/kaggle/input/**/jobs.json", recursive=True)
    assert hits, "No jobs. Build this notebook with `python -m pipeline export music`."
    JOBS = json.load(open(hits[0]))["jobs"]
print(len(JOBS), "job(s):", [j["key"] for j in JOBS])

OUT = "/kaggle/working/out" if os.path.isdir("/kaggle/working") else os.path.abspath("out")
os.makedirs(OUT, exist_ok=True)
ROOT = "/tmp/ACE-Step-1.5"  # code + checkpoints outside /kaggle/working, so they are not saved as output
TAG = JOBS[0]["repo_tag"]
os.environ.setdefault("HF_HOME", "/tmp/hf")

import socket
try:  # fail in seconds, not after minutes of retries (first run: no internet, FAILURES F10)
    socket.gethostbyname("github.com")
except OSError as exc:
    raise RuntimeError("No internet in this session. Kaggle: phone-verify the account "
                       "(Settings → Phone verification) and turn Internet on.") from exc

def pip(*args):
    print("pip install", *args)
    return subprocess.run([sys.executable, "-m", "pip", "install", "-q", *args]).returncode

# %%
# Install: the tagged release, its dependencies except the torch trio (keep Kaggle's CUDA build)
# and nano-vllm (only the language model needs it, and pip cannot see its uv-only local path).
import tomllib

if not os.path.isdir(ROOT):
    subprocess.run(["git", "clone", "--depth", "1", "--branch", TAG,
                    "https://github.com/ace-step/ACE-Step-1.5.git", ROOT], check=True)
COMMIT = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
deps = tomllib.load(open(f"{ROOT}/pyproject.toml", "rb"))["project"]["dependencies"]
SKIP = {"torch", "torchvision", "torchaudio", "nano-vllm", "flash-attn", "flash_attn"}
keep = [d for d in deps if re.split(r"[\s<>=!;\[~]", d, maxsplit=1)[0].strip().lower() not in SKIP]
print("installing", len(keep), "dependencies; skipped:", sorted(SKIP))
pip(*keep)
pip("--no-deps", "--ignore-requires-python", "-e", ROOT)
pip("soundfile")

# %%
# The generator, run as its own process (a clean import after any repair).
WORKER = r'''
import dataclasses, inspect, json, os, shutil, sys, tempfile, time, traceback
from datetime import datetime, timezone
jobs_path, out_dir, root, commit = sys.argv[1:5]
sys.path.insert(0, root)
os.environ.setdefault("ACESTEP_INIT_LLM", "false")
import torch
import soundfile as sf
from acestep.handler import AceStepHandler
from acestep.inference import GenerationConfig, GenerationParams, generate_music

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def build(cls, **kw):
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(kw) - names)
    if unknown:
        print(f"note: {cls.__name__} has no fields {unknown} (ignored)")
    return cls(**{k: v for k, v in kw.items() if k in names})

jobs = json.load(open(jobs_path))
gpu = torch.cuda.get_device_name(0)
versions = {"torch": torch.__version__, "ace_step_tag": jobs[0]["repo_tag"], "ace_step_commit": commit,
            "python": sys.version.split()[0]}
print(gpu, versions, flush=True)

dit = AceStepHandler()
init_kw = dict(project_root=root, config_path=jobs[0]["variant"], device="cuda")
accepted = inspect.signature(dit.initialize_service).parameters
t0 = time.time()
status = dit.initialize_service(**{k: v for k, v in init_kw.items() if k in accepted})
print("initialize_service:", status, f"({time.time() - t0:.0f}s)", flush=True)
if isinstance(status, tuple) and len(status) >= 2 and status[1] is False:
    raise RuntimeError(f"ACE-Step init failed: {status[0]}")

for job in jobs:
    name = f"{job['key']}__{job['hash']}"
    if os.path.exists(os.path.join(out_dir, name + ".json")):
        print("already done:", name); continue
    settings = {k: job[k] for k in ("variant", "steps", "shift", "bpm", "keyscale", "duration_s", "thinking")}
    side = {"key": job["key"], "hash": job["hash"], "gpu": gpu, "settings": settings, "versions": versions,
            "started_at": now()}
    t0 = time.time()
    try:
        params = build(GenerationParams, task_type="text2music", caption=job["caption"],
                       lyrics="[Instrumental]", instrumental=job["instrumental"], bpm=job["bpm"],
                       keyscale=job["keyscale"] or "", duration=float(job["duration_s"]),
                       inference_steps=job["steps"], shift=job["shift"], seed=job["seed"],
                       thinking=job["thinking"], use_cot_metas=False, use_cot_caption=False,
                       use_cot_language=False)
        config = build(GenerationConfig, batch_size=1, use_random_seed=False, seeds=[job["seed"]],
                       audio_format="wav")
        tmp = tempfile.mkdtemp()
        result = generate_music(dit, None, params, config, save_dir=tmp)
        if not getattr(result, "success", True) or not result.audios:
            raise RuntimeError(f"generation failed: {getattr(result, 'error', None) or result.status_message}")
        audio = result.audios[0]
        dest = os.path.join(out_dir, name + ".wav")
        if audio.get("path") and os.path.exists(audio["path"]):
            shutil.move(audio["path"], dest)
        else:
            sf.write(dest, audio["tensor"].float().cpu().numpy().T, audio["sample_rate"])
        info = sf.info(dest)
        side.update(status="ok", file=name + ".wav", audio_seconds=round(info.duration, 2),
                    sample_rate=info.samplerate, channels=info.channels,
                    status_message=str(getattr(result, "status_message", ""))[:500])
    except Exception as exc:
        side.update(status="error", error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-3000:])
    side.update(seconds=round(time.time() - t0, 1), finished_at=now())
    json.dump(side, open(os.path.join(out_dir, name + ".json"), "w"), indent=2)
    print(job["key"], side["status"], side["seconds"], "s", side.get("error") or "", flush=True)
'''
open("/tmp/ace_worker.py", "w").write(WORKER)
json.dump(JOBS, open("/tmp/ace_jobs.json", "w"))

def run_worker():
    proc = subprocess.run([sys.executable, "/tmp/ace_worker.py", "/tmp/ace_jobs.json", OUT, ROOT, COMMIT],
                          capture_output=True, text=True)
    print(proc.stdout[-6000:]); print(proc.stderr[-6000:])
    return proc

# %%
# Run; on a startup failure repair once (missing module, or a too-old PyTorch) and retry.
log = []
for attempt in range(3):
    t0 = time.time()
    proc = run_worker()
    log.append({"attempt": attempt + 1, "returncode": proc.returncode, "seconds": round(time.time() - t0, 1)})
    if proc.returncode == 0:
        break
    missing = re.findall(r"No module named '([\w\.]+)'", proc.stderr)
    if missing:
        pip(missing[-1].split(".")[0].replace("_", "-"))
    elif attempt == 0 and re.search(r"module 'torch'|torch\._|requires? torch|torch>=|torchao", proc.stderr):
        # the repo's own pin, from the PyTorch index (only if Kaggle's build is too old)
        pip("torch==2.10.0", "torchaudio==2.10.0", "torchvision==0.25.0",
            "--index-url", "https://download.pytorch.org/whl/cu128")
    else:
        break
json.dump({"tag": TAG, "commit": COMMIT, "attempts": log}, open(os.path.join(OUT, "notebook_run.json"), "w"), indent=2)
print(sorted(os.listdir(OUT)))
