"""Generated illustrated B-roll via ComfyUI (SDXL + a storybook LoRA) + a cheap
Ken Burns pan — a fixed-cost alternative to photoreal LTX video for the
storybook/book-summary look.

Per scene it generates ONE hand-drawn watercolor illustration (SDXL base +
StoryBookRedmond LoRA, VAE-fp16-fix), then animates the still into a
scene-length 9:16 clip with an ffmpeg crop-pan (zoompan is ~100x slower on an
8 GB card, so we pan a slightly-oversized still — ~1.6s/clip vs ~120s). Writes
clips/scene_XXX.mp4, so the render stage assembles it unchanged.

Style + a byte-identical character string across scenes (plus the LoRA) are what
keep the art cohesive; the per-scene `broll_prompt` (written illustrated by the
video-script skill) drives the content. Selected when footage.broll.engine ==
"image". Prompts stay English (CLIP); Arabic never enters the image prompt.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.parse
import uuid
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

from pipeline import contract
from pipeline.contract import ffmpeg_path
from pipeline.errors import StageError

STAGE = "footage"

# The LoRA trigger word must appear in the prompt; the negative locks the style.
LORA_TRIGGER = "Stickers, sticker"   # StickersRedmond LoRA activation
DEFAULT_STYLE_SUFFIX = (
    "children's picture book illustration, flat cel-shaded coloring, bold clean black "
    "ink outlines, soft pastel colors, minimal shading, plenty of white negative space, "
    "airy uncluttered background, whimsical simple character design, big round friendly "
    "eyes, clean vector-style linework, bright even lighting"
)
DEFAULT_NEGATIVE = (
    "painterly, oil painting, thick impasto, heavy brush texture, canvas texture, "
    "paper grain, watercolor bleed, muddy colors, dark, moody, low-key lighting, "
    "dramatic shadows, sepia, gritty, grunge, cluttered background, busy background, "
    "dense detail, cross-hatching, sketchy rough lineart, blurry lines, photorealistic, "
    "realistic, 3d render, cgi, sticker die-cut border, white outline border, vinyl "
    "decal edge, logo, badge, frame, border, text, watermark, signature, extra limbs, "
    "extra fingers, deformed hands, disfigured face, low quality, jpeg artifacts"
)

_HTTP_TIMEOUT = 30
_POLL_TIMEOUT = 300  # one still on 8 GB SDXL is ~15-25s; big margin


class ComfyImageBroll:
    """SDXL + storybook-LoRA illustration generator over a headless ComfyUI,
    with an ffmpeg crop-pan turning each still into a scene-length clip."""

    def __init__(self, *, url: str, checkpoint: str, lora: str, lora_strength: float,
                 vae: str, width: int, height: int, steps: int, cfg: float,
                 sampler: str, scheduler: str, negative: str, style_suffix: str,
                 out_width: int, out_height: int, fps: int, max_seconds: float) -> None:
        self.url = url.rstrip("/")
        self.checkpoint = checkpoint
        self.lora = lora
        self.lora_strength = lora_strength
        self.vae = vae
        self.width = width
        self.height = height
        self.steps = steps
        self.cfg = cfg
        self.sampler = sampler
        self.scheduler = scheduler
        self.negative = negative
        self.style_suffix = style_suffix
        self.out_width = out_width
        self.out_height = out_height
        self.fps = fps
        self.max_seconds = max_seconds

    # -- workflow (SDXL base + LoRA + fp16-fix VAE txt2img -> SaveImage) ----
    def _workflow(self, prompt: str, seed: int) -> dict:
        return {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": self.checkpoint}},
            "2": {"class_type": "LoraLoader",
                  "inputs": {"model": ["1", 0], "clip": ["1", 1],
                             "lora_name": self.lora,
                             "strength_model": self.lora_strength,
                             "strength_clip": self.lora_strength}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": self.vae}},
            "4": {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["2", 1], "text": prompt}},
            "5": {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["2", 1], "text": self.negative}},
            "6": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": self.width, "height": self.height, "batch_size": 1}},
            "7": {"class_type": "KSampler",
                  "inputs": {"model": ["2", 0], "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0], "seed": seed, "steps": self.steps,
                             "cfg": self.cfg, "sampler_name": self.sampler,
                             "scheduler": self.scheduler, "denoise": 1.0}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveImage",
                  "inputs": {"images": ["8", 0], "filename_prefix": "vf_img"}},
        }

    # -- HTTP (shape mirrors broll_comfy) ---------------------------------
    def _post(self, path: str, obj: dict) -> dict:
        try:
            r = requests.post(self.url + path, json=obj, timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise StageError(STAGE, f"ComfyUI not reachable at {self.url} ({exc}). "
                                    f"See docs/ai-video/GENERATED_BROLL.md") from exc

    def _get(self, path: str) -> dict:
        r = requests.get(self.url + path, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _generate_still(self, prompt: str, seed: int) -> bytes:
        res = self._post("/prompt", {"prompt": self._workflow(prompt, seed),
                                     "client_id": uuid.uuid4().hex})
        if res.get("node_errors"):
            raise StageError(STAGE, f"ComfyUI rejected the image workflow: "
                                    f"{json.dumps(res['node_errors'])[:400]}")
        pid = res.get("prompt_id")
        if not pid:
            raise StageError(STAGE, f"ComfyUI /prompt gave no prompt_id: {res}")
        deadline = time.time() + _POLL_TIMEOUT
        while True:
            hist = self._get(f"/history/{pid}")
            if pid in hist:
                break
            if time.time() > deadline:
                raise StageError(STAGE, f"image generation timed out ({_POLL_TIMEOUT}s)")
            time.sleep(1)
        for out in hist[pid].get("outputs", {}).values():
            for it in out.get("images", []):
                if it.get("filename", "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    q = urllib.parse.urlencode({"filename": it["filename"],
                                                "subfolder": it.get("subfolder", ""),
                                                "type": it.get("type", "output")})
                    r = requests.get(self.url + "/view?" + q, timeout=120)
                    r.raise_for_status()
                    return r.content
        raise StageError(STAGE, "ComfyUI produced no image output")

    # -- public: still -> scene-length crop-pan clip ----------------------
    def generate(self, prompt: str, out_mp4: Path, seed: int, duration: float) -> None:
        still = _trim_flat_border(self._generate_still(prompt, seed))
        dur = max(1.0, min(float(duration), self.max_seconds))
        _ken_burns(still, out_mp4, dur, self.fps, self.out_width, self.out_height, seed)


# -- module helpers -----------------------------------------------------------
def _trim_flat_border(png: bytes, *, white: int = 252, frac: float = 0.97,
                      max_trim: float = 0.14) -> bytes:
    """Crop the flat, near-pure-white die-cut band the StickersRedmond LoRA
    occasionally leaves along ONE edge (a "sticker" margin) — otherwise the Ken
    Burns pan drifts it into frame as a white bar (measured up to ~9% on a bad
    seed). A row/col counts as margin only if ≥`frac` of its pixels are
    near-pure white (≥`white`); real content, pale sky gradients and snowy
    scenes carry linework/shadow, so they never reach that purity and are left
    untouched. Trims at most `max_trim` per side (a full-bleed still returns
    unchanged). English-only stills; no text involved. Best-effort: anything
    that will not decode as an image is returned unchanged (trim is cosmetic,
    never fatal)."""
    try:
        img = Image.open(BytesIO(png)).convert("RGB")
    except Exception:
        return png
    w, h = img.size
    px = img.convert("L").load()

    def is_white_col(x: int) -> bool:
        whites = sum(1 for y in range(0, h, 3) if px[x, y] >= white)
        return whites / len(range(0, h, 3)) >= frac

    def is_white_row(y: int) -> bool:
        whites = sum(1 for x in range(0, w, 3) if px[x, y] >= white)
        return whites / len(range(0, w, 3)) >= frac

    def run(n: int, is_white) -> int:
        got = 0
        for i in range(n):
            if is_white(i):
                got = i + 1
            else:
                break
        return got

    left = run(int(w * max_trim), is_white_col)
    right = run(int(w * max_trim), lambda i: is_white_col(w - 1 - i))
    top = run(int(h * max_trim), is_white_row)
    bottom = run(int(h * max_trim), lambda i: is_white_row(h - 1 - i))
    if not (left or right or top or bottom):
        return png
    out = BytesIO()
    img.crop((left, top, w - right, h - bottom)).save(out, format="PNG")
    return out.getvalue()



def _ken_burns(png: bytes, out_mp4: Path, dur: float, fps: int,
               w: int, h: int, seed: int) -> None:
    """Animate a still into a `dur`-second w:h clip via a cheap crop-pan
    (zoompan is far too slow on 8 GB). Pan direction varies with seed so
    consecutive scenes don't all drift the same way."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    bw, bh = int(w * 1.18), int(h * 1.18)   # oversize for pan headroom
    dx, dy = bw - w, bh - h
    # four gentle diagonal directions
    x_from, x_to, y_from, y_to = {
        0: (0, dx, 0, dy), 1: (dx, 0, dy, 0),
        2: (0, dx, dy, 0), 3: (dx, 0, 0, dy),
    }[seed % 4]
    xe = f"({x_from}+({x_to}-{x_from})*t/{dur:.3f})"
    ye = f"({y_from}+({y_to}-{y_from})*t/{dur:.3f})"
    with tempfile.TemporaryDirectory(prefix="img-") as tmp:
        src = Path(tmp) / "still.png"
        src.write_bytes(png)
        vf = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,"
              f"crop={bw}:{bh},crop={w}:{h}:x='{xe}':y='{ye}',"
              f"fps={fps},format=yuv420p")
        cmd = [ffmpeg_path("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
               "-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(src),
               "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(out_mp4)]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise StageError(STAGE, f"ken-burns render failed: {proc.stderr.strip()[:300]}")


def build(fcfg: dict) -> ComfyImageBroll:
    """Construct from config `footage.broll` (image-engine keys), with the
    research-validated SDXL + StoryBookRedmond defaults."""
    b = (fcfg.get("broll") or {})
    img = (b.get("image") or {})
    return ComfyImageBroll(
        url=str(b.get("comfy_url", "http://127.0.0.1:8188")),
        checkpoint=str(img.get("checkpoint", "sd_xl_base_1.0.safetensors")),
        lora=str(img.get("lora", "StickersRedmond.safetensors")),
        lora_strength=float(img.get("lora_strength", 0.72)),
        vae=str(img.get("vae", "sdxl_vae.safetensors")),
        width=int(img.get("width", 768)),
        height=int(img.get("height", 1344)),
        steps=int(img.get("steps", 26)),
        cfg=float(img.get("cfg", 6.0)),
        sampler=str(img.get("sampler", "dpmpp_2m")),
        scheduler=str(img.get("scheduler", "karras")),
        negative=str(img.get("negative", DEFAULT_NEGATIVE)),
        style_suffix=str(img.get("style_suffix", DEFAULT_STYLE_SUFFIX)),
        out_width=int(b.get("out_width", 1080)),
        out_height=int(b.get("out_height", 1920)),
        fps=int(b.get("fps", 30)),
        max_seconds=float(b.get("max_seconds", 12.0)),
    )


def prompt_for_scene(scene: dict, style_suffix: str = DEFAULT_STYLE_SUFFIX) -> str:
    """Illustrated SDXL prompt: LoRA trigger + the scene's visual CONTENT + the
    engine's style. The video-script skill writes broll_prompt as
    "STYLE LEAD-IN — CONTENT"; strip that lead-in so its (possibly heavier)
    style words don't fight this engine's configured look, then always append
    style_suffix. Falls back to keywords. English only."""
    core = str(scene.get("broll_prompt") or "").strip()
    if core:
        if "—" in core:                       # drop the skill's "STYLE — " lead-in
            core = core.split("—", 1)[1].strip()
    else:
        sets = scene.get("keywords") or []
        core = ", ".join(sets[0]) if sets and sets[0] else "a quiet scene"
    return f"{LORA_TRIGGER}, {core}, {style_suffix}"
