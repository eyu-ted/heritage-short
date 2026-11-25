# %% [markdown]
# # Buna: Wan 2.2 TI2V-5B image-to-video clips (Kaggle)
#
# Do not edit the jobs by hand. `python -m pipeline export wan` builds this notebook from
# `notebooks/wan_shots.py` and writes the jobs (keyframe, prompt, seed, settings, hash) into the
# `JOBS` cell.
#
# **Run it:** Kaggle → Create → Import Notebook → this file. Settings: Accelerator **GPU T4 x2**
# (any 16 GB GPU works), Internet **on**. Then **Save Version → Save & Run All (Commit)**. It
# runs in the background; you can close the tab.
#
# **Bring the clips home:** open the version → Output → download `out/`, then run
# `python -m pipeline ingest wan --from <the download>`.
#
# How it saves memory on a 16 GB GPU: the big text encoder (UMT5-XXL) runs once on the **CPU**
# for all prompts and is then freed. The video model is loaded in fp16 when the GPU has no native
# bf16 (T4/P100) and in bf16 otherwise, with model CPU offload and VAE tiling.
#
# How it fails safely:
# - A tiny preflight run tests the whole path (and fp16 NaNs) before any long job.
# - Each clip is saved as soon as it is done, with a JSON sidecar (job hash, GPU seconds, GPU name).
# - A failed job writes an error sidecar and the next job continues.

# %%
JOBS = None  # filled in by `python -m pipeline export wan`

# %%
import glob, json, os, subprocess, sys, time

if JOBS is None:  # fallback: a jobs.json attached as a dataset
    hits = glob.glob("/kaggle/input/**/jobs.json", recursive=True)
    assert hits, "No jobs. Build this notebook with `python -m pipeline export wan`."
    JOBS = json.load(open(hits[0]))["jobs"]
print(len(JOBS), "job(s):", [j["key"] for j in JOBS])

OUT = "/kaggle/working/out" if os.path.isdir("/kaggle/working") else os.path.abspath("out")
os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("HF_HOME", "/tmp/hf")  # model weights stay out of the saved output

import socket
try:  # fail in seconds, not after minutes of pip retries (first run: no internet, FAILURES F10)
    socket.gethostbyname("huggingface.co")
except OSError as exc:
    raise RuntimeError("No internet in this session. Kaggle: phone-verify the account "
                       "(Settings → Phone verification) and turn Internet on.") from exc

# %%
def pip(*args):
    print("pip install", *args)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *args], check=True)

pip("-U", "diffusers>=0.35.0")  # Wan 2.2 support
pip("transformers>=4.51", "accelerate", "ftfy", "imageio", "imageio-ffmpeg", "sentencepiece")

# %%
import base64, gc, inspect, io, traceback
from datetime import datetime, timezone

import imageio
import numpy as np
import torch
import diffusers, transformers
from PIL import Image
from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, WanTransformer3DModel
from transformers import AutoTokenizer, UMT5EncoderModel

MODEL = JOBS[0]["model"]
GPU = torch.cuda.get_device_name(0)
CAP = torch.cuda.get_device_capability(0)
DTYPE = torch.bfloat16 if CAP[0] >= 8 else torch.float16  # T4 = 7.5, P100 = 6.0: no native bf16
VERSIONS = {"torch": torch.__version__, "diffusers": diffusers.__version__,
            "transformers": transformers.__version__, "python": sys.version.split()[0]}
print(GPU, CAP, "gpus:", torch.cuda.device_count(), "dtype:", DTYPE, VERSIONS)

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def note(event):
    event["ts"] = now()
    with open(os.path.join(OUT, "notebook_log.jsonl"), "a") as fh:
        fh.write(json.dumps(event) + "\n")
    print(event)

# %%
# 1) Text embeddings for every prompt, computed once on the CPU (bf16 is safe for T5 on CPU;
#    fp16 T5 overflows), then the 11 GB encoder is freed before the video model loads.
MAX_TOKENS = 512  # the Wan pipelines' max_sequence_length

def t5_embed(text):
    """Same steps as diffusers' WanPipeline._get_t5_prompt_embeds: encode, cut at the real
    length, zero-pad to 512 tokens."""
    t = tokenizer([" ".join(text.split())], padding="max_length", max_length=MAX_TOKENS, truncation=True,
                  add_special_tokens=True, return_attention_mask=True, return_tensors="pt")
    seq_len = int(t.attention_mask.gt(0).sum())
    emb = text_encoder(t.input_ids, t.attention_mask).last_hidden_state.float()[0, :seq_len]
    return torch.cat([emb, emb.new_zeros(MAX_TOKENS - seq_len, emb.size(1))])[None]

t0 = time.time()
tokenizer = AutoTokenizer.from_pretrained(MODEL, subfolder="tokenizer")
text_encoder = UMT5EncoderModel.from_pretrained(MODEL, subfolder="text_encoder", torch_dtype=torch.bfloat16)
EMBEDS = {}
with torch.no_grad():
    for job in JOBS:
        EMBEDS[job["key"]] = (t5_embed(job["prompt"]), t5_embed(job["negative_prompt"]))
        assert torch.isfinite(EMBEDS[job["key"]][0]).all(), "text embedding has NaN/inf"
del text_encoder
gc.collect()
note({"event": "text_encoded", "seconds": round(time.time() - t0, 1), "jobs": len(JOBS)})

# %%
# 2) The video pipeline without a text encoder.
def load_pipe(dtype):
    vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32)
    transformer = WanTransformer3DModel.from_pretrained(MODEL, subfolder="transformer", torch_dtype=dtype)
    sched_cfg = diffusers.UniPCMultistepScheduler.load_config(MODEL, subfolder="scheduler")
    scheduler = getattr(diffusers, sched_cfg["_class_name"]).from_config(sched_cfg)
    params = inspect.signature(WanImageToVideoPipeline.__init__).parameters
    if "expand_timesteps" not in params:
        raise RuntimeError(f"diffusers {diffusers.__version__} has no Wan 2.2 TI2V support (expand_timesteps)")
    kwargs = dict(tokenizer=tokenizer, text_encoder=None, vae=vae, scheduler=scheduler,
                  transformer=transformer, expand_timesteps=True)
    for optional in ("image_encoder", "image_processor", "transformer_2"):
        if optional in params:
            kwargs[optional] = None
    pipe = WanImageToVideoPipeline(**kwargs)
    pipe.enable_model_cpu_offload()
    try:
        pipe.vae.enable_tiling()
    except Exception as exc:  # older diffusers: no tiling for this VAE
        print("vae tiling not available:", exc)
    return pipe

def generate(pipe, job, size, frames, steps, dtype):
    image = Image.open(io.BytesIO(base64.b64decode(job["image_b64"]))).convert("RGB").resize((size, size), Image.LANCZOS)
    pe, ne = EMBEDS[job["key"]]
    out = pipe(image=image, prompt_embeds=pe.to(dtype), negative_prompt_embeds=ne.to(dtype),
               height=size, width=size, num_frames=frames, num_inference_steps=steps,
               guidance_scale=job["guidance"], generator=torch.Generator("cpu").manual_seed(job["seed"]),
               output_type="np").frames[0]
    return np.asarray(out)

def bad_frames(frames):
    return bool(np.isnan(frames).any() or frames.max() < 0.02)

pipe = load_pipe(DTYPE)

# %%
# 3) Preflight: a tiny clip through the whole path; if fp16 gives NaN/black, switch to bf16.
for attempt in range(2):
    t0 = time.time()
    try:
        tiny = generate(pipe, JOBS[0], size=256, frames=17, steps=2, dtype=DTYPE)
        ok = not bad_frames(tiny)
        err = None if ok else "NaN or black frames"
    except Exception as exc:
        ok, err = False, f"{type(exc).__name__}: {exc}"
    note({"event": "preflight", "ok": ok, "dtype": str(DTYPE), "seconds": round(time.time() - t0, 1), "error": err})
    if ok:
        break
    if DTYPE == torch.float16 and attempt == 0:
        DTYPE = torch.bfloat16
        del pipe; gc.collect(); torch.cuda.empty_cache()
        pipe = load_pipe(DTYPE)
    else:
        raise RuntimeError(f"preflight failed: {err}")

# %%
# 4) The real clips, one at a time, each saved as soon as it exists.
for job in JOBS:
    name = f"{job['key']}__{job['hash']}"
    settings = {k: job[k] for k in ("size", "frames", "steps", "guidance", "fps")}
    side = {"key": job["key"], "hash": job["hash"], "gpu": GPU, "dtype": str(DTYPE), "settings": settings,
            "versions": VERSIONS, "started_at": now()}
    if os.path.exists(os.path.join(OUT, name + ".json")):
        print("already done:", name)
        continue
    t0 = time.time()
    try:
        frames = generate(pipe, job, job["size"], job["frames"], job["steps"], DTYPE)
        if bad_frames(frames):
            raise RuntimeError("NaN or black frames")
        u8 = (np.clip(frames, 0, 1) * 255).round().astype(np.uint8)
        imageio.mimwrite(os.path.join(OUT, name + ".mp4"), list(u8), fps=job["fps"], codec="libx264",
                         quality=9, macro_block_size=1, ffmpeg_params=["-pix_fmt", "yuv420p"])
        side.update(status="ok", file=name + ".mp4", frames_written=int(len(u8)))
    except Exception as exc:
        side.update(status="error", error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-3000:])
    side.update(seconds=round(time.time() - t0, 1), finished_at=now(),
                peak_vram_gb=round(torch.cuda.max_memory_allocated() / 1e9, 2))
    with open(os.path.join(OUT, name + ".json"), "w") as fh:
        json.dump(side, fh, indent=2)
    note({"event": "clip", "key": job["key"], "status": side["status"], "seconds": side["seconds"],
          "error": side.get("error")})
    torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()

print(sorted(os.listdir(OUT)))
