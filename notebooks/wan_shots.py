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
# **Or on Google Colab (free T4):** File → Upload notebook → this file; Runtime → Change runtime
# type → **T4 GPU**; Runtime → **Run all**. When it finishes, the last cell writes `out.zip`:
# download it from the Files panel (folder icon on the left). If the session crashes or restarts,
# just Run all again: finished clips are skipped and the weights are already downloaded.
#
# How it saves memory on a 16 GB GPU: the big text encoder (UMT5-XXL) runs once for all prompts
# and is then freed. The video model is loaded in fp16 when the GPU has no native bf16 (T4/P100)
# and in bf16 otherwise, with VAE tiling.
# - Plenty of RAM (Kaggle, ~30 GB): the text encoder runs on the CPU, the video model uses model
#   CPU offload.
# - Little RAM (free Colab, ~12.7 GB, less than either big model): both load **straight onto the
#   GPU**, never through RAM, and the video model stays there (no offload). Loading them through
#   RAM is what crashed the first Colab run.
# - Both: the clips are made in two phases. First every clip is denoised and its latents saved to
#   disk; then the video model is freed and the VAE alone decodes them. On a T4 the two do not fit
#   together.
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
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")  # less fragmentation (set before torch)

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
if not torch.cuda.is_available():  # Colab's CPU runtime ships a CPU-only torch: "not compiled with CUDA"
    raise RuntimeError("No GPU in this session. Colab: Runtime → Change runtime type → T4 GPU → Save, then "
                       "Run all. If Colab says it cannot connect to a GPU, the free GPU quota is used up for now. "
                       "Kaggle: Settings → Accelerator → GPU T4 x2.")
GPU = torch.cuda.get_device_name(0)
CAP = torch.cuda.get_device_capability(0)
DTYPE = torch.bfloat16 if CAP[0] >= 8 else torch.float16  # T4 = 7.5, P100 = 6.0: no native bf16
VERSIONS = {"torch": torch.__version__, "diffusers": diffusers.__version__,
            "transformers": transformers.__version__, "python": sys.version.split()[0]}
RAM_GB = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
VRAM_GB = torch.cuda.get_device_properties(0).total_memory / 1e9
LOW_RAM = RAM_GB < 24  # see the top: Colab's 12.7 GB cannot hold the 11 GB text encoder or the 10 GB video model
ON_GPU = {"device_map": {"": 0}}  # load weights shard by shard straight onto GPU 0
print(GPU, CAP, "gpus:", torch.cuda.device_count(), "dtype:", DTYPE, VERSIONS)
print(f"RAM {RAM_GB:.1f} GB, VRAM {VRAM_GB:.1f} GB:", "low-RAM mode (weights load straight onto the GPU)"
      if LOW_RAM else "normal mode (text encoder on CPU, video model with CPU offload)")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def note(event):
    event["ts"] = now()
    with open(os.path.join(OUT, "notebook_log.jsonl"), "a") as fh:
        fh.write(json.dumps(event) + "\n")
    print(event)

# %%
# 1) Text embeddings for every prompt, computed once, then the 11 GB encoder is freed before the
#    video model loads. bf16 is safe for T5; plain fp16 T5 can overflow, so fp16 is only the last
#    resort on the GPU (UMT5 clamps inf in fp16) and every embedding is checked for NaN/inf.
MAX_TOKENS = 512  # the Wan pipelines' max_sequence_length

def t5_embed(encoder, text, device):
    """Same steps as diffusers' WanPipeline._get_t5_prompt_embeds: encode, cut at the real
    length, zero-pad to 512 tokens. Returned on the CPU in fp32."""
    t = tokenizer([" ".join(text.split())], padding="max_length", max_length=MAX_TOKENS, truncation=True,
                  add_special_tokens=True, return_attention_mask=True, return_tensors="pt")
    seq_len = int(t.attention_mask.gt(0).sum())
    emb = encoder(t.input_ids.to(device), t.attention_mask.to(device)).last_hidden_state.float().cpu()[0, :seq_len]
    emb = torch.cat([emb, emb.new_zeros(MAX_TOKENS - seq_len, emb.size(1))])[None]
    if not torch.isfinite(emb).all():
        raise ValueError("text embedding has NaN/inf")
    return emb

# (device, dtype) plans, tried in order. T4 has no native bf16, but PyTorch runs it (slower).
TEXT_PLANS = [("cuda", torch.bfloat16), ("cuda", torch.float16)] if LOW_RAM else [("cpu", torch.bfloat16)]
# A re-run in the same session ("Run all" again) still holds the last video model on the GPU
# (12 GB of a T4's 14.5): free it first, or the text encoder does not fit.
for leftover in ("pipe", "tiny", "frames"):
    globals().pop(leftover, None)
gc.collect(); torch.cuda.empty_cache()
t0 = time.time()
tokenizer = AutoTokenizer.from_pretrained(MODEL, subfolder="tokenizer")
EMBEDS = None
for device, text_dtype in TEXT_PLANS:
    text_encoder = None
    try:
        text_encoder = UMT5EncoderModel.from_pretrained(MODEL, subfolder="text_encoder", torch_dtype=text_dtype,
                                                        **(ON_GPU if device == "cuda" else {}))
        with torch.no_grad():
            EMBEDS = {job["key"]: (t5_embed(text_encoder, job["prompt"], device),
                                   t5_embed(text_encoder, job["negative_prompt"], device)) for job in JOBS}
        TEXT_PLAN = f"{device}/{text_dtype}"
        break
    except Exception as exc:
        note({"event": "text_encoder_failed", "plan": f"{device}/{text_dtype}", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        del text_encoder
        gc.collect(); torch.cuda.empty_cache()
assert EMBEDS is not None, "text encoding failed with every plan (see the notes above)"
note({"event": "text_encoded", "plan": TEXT_PLAN, "seconds": round(time.time() - t0, 1), "jobs": len(JOBS)})

# %%
# 2) The video pipeline without a text encoder.
class GpuPipe(WanImageToVideoPipeline):
    """Low-RAM path: the transformer stays on the GPU, the VAE does not (see load_pipe), so the
    pipeline's own guess of its device could say "cpu". Work always happens on the GPU."""
    @property
    def _execution_device(self):
        return torch.device("cuda")

def vae_on_gpu_during(pipe, fn):
    """Run fn with the VAE on the GPU, then send it back to the CPU. The fp16 transformer (~9.3 GiB)
    plus the fp32 VAE (~2.7 GiB) left a T4 too little room to denoise: the first Colab run had all
    3 clips fail with CUDA OOM in the first step. The VAE is only needed to encode the keyframe
    (prepare_latents) and to decode at the end."""
    def run(*args, **kwargs):
        pipe.vae.to("cuda")
        # The pipeline moves the latents to the VAE's device BEFORE calling vae.decode, while the
        # VAE is still on the CPU (Colab attempt 5: "slow_conv3d_forward ... CUDA"). Bring them back.
        args = [a.to("cuda") if torch.is_tensor(a) else a for a in args]
        kwargs = {k: v.to("cuda") if torch.is_tensor(v) else v for k, v in kwargs.items()}
        try:
            return fn(*args, **kwargs)
        finally:
            pipe.vae.to("cpu")
            torch.cuda.empty_cache()
    return run

STASH = {}

def stash_decode(*args, **kwargs):
    """Stands in for the pipeline's vae.decode: keep the finished latents (already mixed with the
    keyframe and de-normalised by the pipeline) and hand back a tiny dummy video. Decoding happens
    later, once the video model is gone. Colab attempt 6: all 30 steps finished, then the decode
    ran out of memory with the 9.3 GiB transformer still on the T4 (unpatchify, 568 MiB short)."""
    z = args[0] if args else kwargs["z"]
    STASH["z"] = z.detach().to("cpu", torch.float32)
    return (torch.zeros(1, 3, 1, 8, 8),)

def decode_latents(vae, z):
    """The real decode (class method, so the stash on the instance is bypassed)."""
    moved = vae.device.type == "cpu" and not hasattr(vae, "_hf_hook")  # low-RAM pipe: VAE parked on CPU
    if moved:
        vae.to("cuda")
    try:
        with torch.no_grad():
            video = type(vae).decode(vae, z.to("cuda", vae.dtype), return_dict=False)[0]
        return np.asarray(VIDEO_PROCESSOR.postprocess_video(video, output_type="np")[0])
    finally:
        if moved:
            vae.to("cpu")
        torch.cuda.empty_cache()

def load_pipe(dtype):
    vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32)
    transformer = WanTransformer3DModel.from_pretrained(MODEL, subfolder="transformer", torch_dtype=dtype,
                                                        **(ON_GPU if LOW_RAM else {}))
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
    pipe = (GpuPipe if LOW_RAM else WanImageToVideoPipeline)(**kwargs)
    if LOW_RAM:
        # The transformer is already on the GPU; the VAE waits on the CPU and visits the GPU twice.
        pipe.prepare_latents = vae_on_gpu_during(pipe, pipe.prepare_latents)
    else:
        pipe.enable_model_cpu_offload()
    pipe.vae.decode = stash_decode  # both paths: denoise now, decode later (decode_latents)
    try:
        pipe.vae.enable_tiling()
    except Exception as exc:  # older diffusers: no tiling for this VAE
        print("vae tiling not available:", exc)
    return pipe

def denoise(pipe, job, size, frames, steps, dtype):
    """Run the pipeline up to the VAE; returns the finished latents (on the CPU)."""
    image = Image.open(io.BytesIO(base64.b64decode(job["image_b64"]))).convert("RGB").resize((size, size), Image.LANCZOS)
    pe, ne = EMBEDS[job["key"]]
    # The embeddings live on the CPU. CPU offload's hooks used to move them; on the GPU-resident
    # path nothing does (preflight: "mat1 is on cpu"), so move them here for both paths.
    STASH.clear()
    pipe(image=image, prompt_embeds=pe.to("cuda", dtype), negative_prompt_embeds=ne.to("cuda", dtype),
         height=size, width=size, num_frames=frames, num_inference_steps=steps,
         guidance_scale=job["guidance"], generator=torch.Generator("cpu").manual_seed(job["seed"]),
         output_type="np")
    if "z" not in STASH:
        raise RuntimeError("the pipeline never reached vae.decode (diffusers changed?)")
    return STASH.pop("z")

def bad_frames(frames):
    return bool(np.isnan(frames).any() or frames.max() < 0.02)

pipe = load_pipe(DTYPE)
VIDEO_PROCESSOR = pipe.video_processor

# %%
# 3) Preflight: a tiny clip through the whole path; if fp16 gives NaN/black, switch to bf16.
for attempt in range(2):
    t0 = time.time()
    try:
        tiny = decode_latents(pipe.vae, denoise(pipe, JOBS[0], size=256, frames=17, steps=2, dtype=DTYPE))
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
        VIDEO_PROCESSOR = pipe.video_processor
    else:
        raise RuntimeError(f"preflight failed: {err}")

# %%
# 4) The real clips in two phases. A: denoise every clip and save its latents (~10 MB each) to disk.
# B: free the video model, load the VAE alone and decode. On a T4 the transformer and the decode
# do not fit together (Colab attempt 6). Saved latents survive a session restart, so Run all resumes.
LAT = os.path.join(os.path.dirname(OUT), "wan_latents")
os.makedirs(LAT, exist_ok=True)

def clip_name(job):
    return f"{job['key']}__{job['hash']}"

def finished(job):  # only a good clip counts; an error sidecar from an earlier run is retried
    path = os.path.join(OUT, clip_name(job) + ".json")
    return os.path.exists(path) and json.load(open(path)).get("status") == "ok"

def write_sidecar(job, **fields):
    settings = {k: job[k] for k in ("size", "frames", "steps", "guidance", "fps")}
    side = {"key": job["key"], "hash": job["hash"], "gpu": GPU, "dtype": str(DTYPE), "settings": settings,
            "versions": VERSIONS, "low_ram": LOW_RAM, "text_plan": TEXT_PLAN, "decode": "deferred",
            "finished_at": now(), **fields}
    with open(os.path.join(OUT, clip_name(job) + ".json"), "w") as fh:
        json.dump(side, fh, indent=2)
    note({"event": "clip", "key": job["key"], "status": side["status"], "seconds": side.get("seconds"),
          "error": side.get("error")})

# Phase A: denoise
for job in JOBS:
    lat_path = os.path.join(LAT, clip_name(job) + ".pt")
    if finished(job) or os.path.exists(lat_path):
        print("already denoised:", clip_name(job))
        continue
    if "pipe" not in globals():
        pipe = load_pipe(DTYPE)
        VIDEO_PROCESSOR = pipe.video_processor
    t0 = time.time()
    torch.cuda.reset_peak_memory_stats()
    try:
        z = denoise(pipe, job, job["size"], job["frames"], job["steps"], DTYPE)
        secs = round(time.time() - t0, 1)
        torch.save({"z": z, "seconds": secs, "dtype": str(DTYPE),
                    "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)}, lat_path)
        note({"event": "denoised", "key": job["key"], "seconds": secs, "latent_shape": list(z.shape)})
    except Exception as exc:
        write_sidecar(job, status="error", stage="denoise", error=f"{type(exc).__name__}: {exc}",
                      trace=traceback.format_exc()[-3000:], seconds=round(time.time() - t0, 1))
    torch.cuda.empty_cache()

# Phase B: decode with the VAE alone on the GPU
todo = [j for j in JOBS if not finished(j) and os.path.exists(os.path.join(LAT, clip_name(j) + ".pt"))]
if todo:
    globals().pop("pipe", None)
    gc.collect(); torch.cuda.empty_cache()
    print(f"video model freed; GPU memory in use: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
    vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32).to("cuda")
    try:
        vae.enable_tiling()
    except Exception as exc:
        print("vae tiling not available:", exc)
for job in todo:
    saved = torch.load(os.path.join(LAT, clip_name(job) + ".pt"))
    t0 = time.time()
    torch.cuda.reset_peak_memory_stats()
    try:
        frames = decode_latents(vae, saved["z"])
        if bad_frames(frames):
            raise RuntimeError("NaN or black frames")
        u8 = (np.clip(frames, 0, 1) * 255).round().astype(np.uint8)
        imageio.mimwrite(os.path.join(OUT, clip_name(job) + ".mp4"), list(u8), fps=job["fps"], codec="libx264",
                         quality=9, macro_block_size=1, ffmpeg_params=["-pix_fmt", "yuv420p"])
        dec = round(time.time() - t0, 1)
        write_sidecar(job, status="ok", file=clip_name(job) + ".mp4", frames_written=int(len(u8)),
                      seconds=round(saved["seconds"] + dec, 1), denoise_seconds=saved["seconds"],
                      decode_seconds=dec, peak_vram_gb=saved["peak_vram_gb"],
                      decode_peak_vram_gb=round(torch.cuda.max_memory_allocated() / 1e9, 2))
    except Exception as exc:
        write_sidecar(job, status="error", stage="decode", error=f"{type(exc).__name__}: {exc}",
                      trace=traceback.format_exc()[-3000:], seconds=round(saved["seconds"] + time.time() - t0, 1))
    torch.cuda.empty_cache()

print(sorted(os.listdir(OUT)))
if not os.path.isdir("/kaggle/working"):  # Colab etc.: one file to download (Files panel → out.zip)
    import shutil
    print("download this:", shutil.make_archive(OUT, "zip", os.path.dirname(OUT), os.path.basename(OUT)))
