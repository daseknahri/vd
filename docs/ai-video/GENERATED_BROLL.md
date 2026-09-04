# Generated B-roll (ComfyUI + LTX-Video)

A **fixed-cost alternative to stock footage**: instead of searching
Pexels/Pixabay, the footage stage generates each scene's clip on the local GPU
with a headless ComfyUI running LTX-Video. Keeps "the only variable cost is
TTS". It slots into the existing footage stage behind `footage.ai_broll`; stock
stays the fallback (flip the flag off).

> **Status (2026-09):** built and proven end-to-end on this machine
> (RTX 3060 Ti, 8 GB) — `footage.run` → ComfyUI LTX-Video → `clips/scene_XXX.mp4`.
> Quality is strong **with descriptive prompts**; see "Prompt quality" — it is
> the main lever and the reason this is opt-in, not the default.

## How it works

```
footage.run (ai_broll: true)
   └─ pipeline/broll_comfy.py  ── REST ──►  headless ComfyUI (:8188)
        per scene: keywords+mood → prompt → LTX-Video T2V workflow
        → SaveWEBM → GET /view → ffmpeg webm→mp4 → clips/scene_XXX.mp4
```

- The LTX workflow (checkpoint + fp8 T5 → EmptyLTXVLatentVideo → ModelSamplingLTXV
  + LTXVScheduler → SamplerCustom → VAEDecode → SaveWEBM) is built in code from
  ComfyUI's real node schemas.
- Generated clips are **silent** B-roll: audio is dropped, and ElevenLabs/
  Chatterbox stay the only voice, Pillow+raqm the only captions
  (CLAUDE.md hard rules 1 & 3). Per-scene failures are recorded in
  `footage_report.json` (status `error`) and never abort the stage.

## Build the ComfyUI env (one time)

Separate from the TTS venv so neither can destabilize the other.

```powershell
git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git D:\vd-ai\ComfyUI
uv venv D:\vd-ai\ComfyUI\venv --python 3.12
# ComfyUI's comfy-kitchen needs torch >= 2.7 (list[int] op schemas) -> use cu128:
uv pip install --python D:\vd-ai\ComfyUI\venv\Scripts\python.exe --torch-backend=cu128 "torch>=2.7" torchvision torchaudio
uv pip install --python D:\vd-ai\ComfyUI\venv\Scripts\python.exe -r D:\vd-ai\ComfyUI\requirements.txt
```

Models (download with `huggingface_hub`; set `HF_HUB_DISABLE_XET=1` if the Xet
CDN 403s). For **8 GB use the fp8 T5** (fp16 won't fit):

| File | Repo | → folder |
|------|------|----------|
| `ltx-video-2b-v0.9.5.safetensors` | `Lightricks/LTX-Video` | `ComfyUI/models/checkpoints/` |
| `t5xxl_fp8_e4m3fn.safetensors` | `comfyanonymous/flux_text_encoders` | `ComfyUI/models/text_encoders/` |

Launch headless (leave it running while you make videos):

```powershell
$env:HF_HOME="D:\vd-ai\models"; D:\vd-ai\ComfyUI\venv\Scripts\python.exe D:\vd-ai\ComfyUI\main.py --port 8188
```

Check it: `GET http://127.0.0.1:8188/system_stats` should report your GPU.

## Enable it

In `config.yaml` (or a project's `project.yaml`):

```yaml
footage:
  ai_broll: true
  broll:
    comfy_url: "http://127.0.0.1:8188"
    steps: 20        # 15 is ~30% faster; 20-30 improves prompt adherence
    # width/height/length/fps/cfg/sampler/checkpoint/t5 also configurable
```

Then run the normal loop; the footage stage generates instead of searching.
Idempotent (existing clips are kept); `redo` deletes a scene's clip and
regenerates a fresh take (random seed).

## Prompt quality — the main lever

LTX rewards **long, descriptive prompts**. The video-script skill's `keywords`
are terse (tuned for stock search), so a bare keyword like `"code"` produces
weak, off-topic clips. Two ways to get good results:

1. **Best:** add a descriptive `broll_prompt` per scene in `script.json`, e.g.
   *"A slow macro push-in on glowing lines of code on a dark monitor, blue and
   orange bokeh, shallow depth of field, cinematic."* `prompt_for_scene` uses it
   verbatim when present. (Natural place to generate these: the video-script
   skill, alongside keywords.)
2. **Fallback:** the built-in template wraps all keyword sets in cinematic
   framing — acceptable for scenic/abstract subjects, weaker for specific ones.

Raising `steps` (20→30) also improves adherence at a time cost.

## Performance & footprint (RTX 3060 Ti, 8 GB)

| | Value |
|---|---|
| VRAM peak | ~4.5 GB (LTX-2B; T5 offloaded after encode) — fits 8 GB |
| Per clip (~4 s, 768×512) | ~112 s @20 steps, ~88 s @15 steps |
| First-ever generation | +one-time CUDA warmup |

A 12-scene video ≈ 18–22 min of generation — unattended, fixed cost. For higher
quality/photoreal humans, **Wan 2.2** is the heavier alternative (tighter on
8 GB); for paid speed/quality, the connected Higgsfield MCP (per-second cost,
breaks fixed-cost — opt-in only).

## Must-do before publishing AI B-roll

Platforms require AI-generated content to be **labeled**. `footage_report.json`
records `status: "generated"`; the publish step must set an AI-generated flag on
`post.json` when any scene was generated. (Not yet wired — publishing is
deferred by Hard Rule 2 regardless.)

## Troubleshooting

- **`StageError: ComfyUI not reachable`** — start the server (above); check
  `comfy_url`.
- **ComfyUI won't start, `infer_schema ... list[int]`** — torch too old for
  `comfy-kitchen`; install `torch>=2.7` (cu128).
- **`ModuleNotFoundError: pkg_resources`** — `uv pip install "setuptools<81"`.
- **CUDA OOM** — lower `width`/`height`/`length`, or `steps`; confirm the **fp8**
  T5 (not fp16) is in `text_encoders/`.
- **Clip is off-topic/blurry** — weak prompt; add a `broll_prompt` and/or raise
  `steps` (see Prompt quality).
