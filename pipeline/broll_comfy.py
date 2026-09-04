"""Generated B-roll via a headless ComfyUI + LTX-Video — a fixed-cost
alternative to Pexels/Pixabay stock for the footage stage.

Drives ComfyUI's REST API (POST /prompt, poll /history, GET /view) with a
LTX-Video text-to-video workflow, then transcodes the result to the
`clips/scene_XXX.mp4` the pipeline expects (via the project's ffmpeg). Keeps the
"only variable cost is TTS" principle: generation is GPU-only. Runs on an 8 GB
card (LTX-2B, ~4.5 GB peak). The footage stage calls this when
`footage.ai_broll` is true; stock stays the fallback.

Generated clips are SILENT B-roll: any model audio is ignored, and ElevenLabs/
Chatterbox remain the only voice and Pillow+raqm the only caption path
(CLAUDE.md hard rules 1 & 3). Output using AI-generated footage must be labeled
as such at publish (platform policy) — footage_report records status
"generated" so downstream can flag it.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path

import requests

from pipeline import contract
from pipeline.contract import ContractError, ffmpeg_path
from pipeline.errors import StageError

STAGE = "footage"

DEFAULT_NEGATIVE = (
    "low quality, worst quality, deformed, distorted, disfigured, "
    "motion blur, watermark, text, logo, jitter, flicker, jpeg artifacts"
)
_HTTP_TIMEOUT = 30
_POLL_TIMEOUT = 900  # seconds to wait for one clip (8 GB LTX ~2 min, big margin)


class ComfyBroll:
    """LTX-Video text-to-video generator over a headless ComfyUI."""

    def __init__(self, *, url: str, checkpoint: str, t5: str, width: int,
                 height: int, length: int, fps: int, steps: int, cfg: float,
                 sampler: str, negative: str) -> None:
        self.url = url.rstrip("/")
        self.checkpoint = checkpoint
        self.t5 = t5
        self.width = width
        self.height = height
        self.length = length
        self.fps = fps
        self.steps = steps
        self.cfg = cfg
        self.sampler = sampler
        self.negative = negative

    # -- workflow (built from ComfyUI's real LTXV node schemas) -----------
    def _workflow(self, prompt: str, seed: int) -> dict:
        return {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": self.checkpoint}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": self.t5, "type": "ltxv", "device": "default"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": self.negative, "clip": ["2", 0]}},
            "5": {"class_type": "EmptyLTXVLatentVideo",
                  "inputs": {"width": self.width, "height": self.height,
                             "length": self.length, "batch_size": 1}},
            "6": {"class_type": "ModelSamplingLTXV",
                  "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95,
                             "latent": ["5", 0]}},
            "7": {"class_type": "LTXVConditioning",
                  "inputs": {"positive": ["3", 0], "negative": ["4", 0],
                             "frame_rate": float(self.fps)}},
            "8": {"class_type": "LTXVScheduler",
                  "inputs": {"steps": self.steps, "max_shift": 2.05, "base_shift": 0.95,
                             "stretch": True, "terminal": 0.1, "latent": ["5", 0]}},
            "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": self.sampler}},
            "10": {"class_type": "SamplerCustom",
                   "inputs": {"model": ["6", 0], "add_noise": True, "noise_seed": seed,
                              "cfg": self.cfg, "positive": ["7", 0], "negative": ["7", 1],
                              "sampler": ["9", 0], "sigmas": ["8", 0], "latent_image": ["5", 0]}},
            "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["1", 2]}},
            "12": {"class_type": "SaveWEBM",
                   "inputs": {"images": ["11", 0], "filename_prefix": "vf_broll",
                              "codec": "vp9", "fps": float(self.fps), "crf": 32.0}},
        }

    # -- HTTP -------------------------------------------------------------
    def _post(self, path: str, obj: dict) -> dict:
        try:
            r = requests.post(self.url + path, json=obj, timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise StageError(
                STAGE,
                f"ComfyUI not reachable at {self.url} ({exc}). Is the server "
                f"running? See docs/ai-video/GENERATED_BROLL.md",
            ) from exc

    def _get(self, path: str) -> dict:
        r = requests.get(self.url + path, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()

    # -- generate one clip ------------------------------------------------
    def generate(self, prompt: str, out_mp4: Path, seed: int) -> None:
        res = self._post("/prompt", {"prompt": self._workflow(prompt, seed),
                                     "client_id": uuid.uuid4().hex})
        if res.get("node_errors"):
            raise StageError(STAGE, f"ComfyUI rejected the workflow: "
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
                raise StageError(STAGE, f"ComfyUI generation timed out after "
                                        f"{_POLL_TIMEOUT}s (prompt {pid})")
            time.sleep(2)

        entry = hist[pid]
        status = (entry.get("status") or {}).get("status_str")
        if status and status != "success":
            raise StageError(STAGE, f"ComfyUI generation failed (status={status})")
        webm = self._fetch_output(entry.get("outputs", {}))
        if webm is None:
            raise StageError(STAGE, "ComfyUI produced no video output")
        _transcode_to_mp4(webm, out_mp4)

    def _fetch_output(self, outputs: dict) -> bytes | None:
        for out in outputs.values():
            for items in out.values():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, dict) and it.get("filename", "").endswith((".webm", ".mp4")):
                        q = urllib.parse.urlencode({
                            "filename": it["filename"],
                            "subfolder": it.get("subfolder", ""),
                            "type": it.get("type", "output")})
                        r = requests.get(self.url + "/view?" + q, timeout=120)
                        r.raise_for_status()
                        return r.content
        return None


# -- module helpers -----------------------------------------------------------
def _transcode_to_mp4(webm: bytes, out_mp4: Path) -> None:
    """webm (vp9) -> H.264 mp4 (the clip format the render stage consumes).
    Also drops any audio track (generated B-roll is silent by contract)."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="broll-") as tmp:
        src = Path(tmp) / "in.webm"
        src.write_bytes(webm)
        cmd = [
            ffmpeg_path("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out_mp4),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise StageError(STAGE, f"broll webm->mp4 failed: {proc.stderr.strip()[:300]}")


def build(fcfg: dict) -> ComfyBroll:
    """Construct from config `footage.broll` (all optional, sensible defaults
    matching the validated 8 GB LTX-2B setup)."""
    b = (fcfg.get("broll") or {})
    return ComfyBroll(
        url=str(b.get("comfy_url", "http://127.0.0.1:8188")),
        checkpoint=str(b.get("checkpoint", "ltx-video-2b-v0.9.5.safetensors")),
        t5=str(b.get("t5", "t5xxl_fp8_e4m3fn.safetensors")),
        width=int(b.get("width", 768)),
        height=int(b.get("height", 512)),
        length=int(b.get("length", 97)),
        fps=int(b.get("fps", 25)),
        steps=int(b.get("steps", 20)),
        cfg=float(b.get("cfg", 3.0)),
        sampler=str(b.get("sampler", "euler")),
        negative=str(b.get("negative", DEFAULT_NEGATIVE)),
    )


def prompt_for_scene(scene: dict) -> str:
    """Build an LTX prompt from a scene's literal-visual keywords + mood.

    LTX rewards LONG, descriptive prompts; the video-script skill's keywords are
    terse (tuned for stock search), so this wraps ALL keyword sets in strong
    cinematic framing to give the model more to work with. For best adherence,
    supply a descriptive per-scene `broll_prompt` in script.json instead (see
    docs/ai-video/GENERATED_BROLL.md) — a bare keyword like "code" alone yields
    weak, off-topic results."""
    if scene.get("broll_prompt"):        # explicit descriptive prompt wins
        return str(scene["broll_prompt"])
    sets = scene.get("keywords") or []
    subjects = [", ".join(s) for s in sets if s]
    subject = "; ".join(subjects) if subjects else "an abstract background"
    mood = str(scene.get("mood", "")).strip()
    mood_part = f"{mood} " if mood else ""
    return (
        f"A cinematic {mood_part}establishing shot of {subject}. Realistic, "
        f"highly detailed, sharp focus, professional cinematography, smooth "
        f"slow camera movement, natural volumetric lighting, shallow depth of "
        f"field, 4k, high quality."
    )
