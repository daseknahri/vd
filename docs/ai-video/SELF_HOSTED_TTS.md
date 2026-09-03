# Self-hosted Arabic TTS (Chatterbox + WhisperX)

An **alternate `voice` provider** that generates the Arabic narration on the
local GPU instead of calling ElevenLabs — turning TTS from the pipeline's only
variable cost into a fixed (GPU-only) cost. It slots behind the existing
`TTSProvider` interface (`pipeline/voice.py`), so `timing.json`, the Pillow+raqm
karaoke captions, `voice_cache/`, and `verify_timing` are all **unchanged**.

> **Status (2026-09):** built and proven end-to-end on this machine
> (RTX 3060 Ti, 8 GB) — synth → forced alignment → `timing.json` → captions.
> ElevenLabs remains the **default**; the open Arabic *quality/dialect* still
> needs your A/B sign-off before it becomes the default (see "Quality gate").

## How it works

```
voice.run  ─►  ChatterboxTTS (pipeline/chatterbox_tts.py, pipeline venv)
                    │  newline-delimited JSON over stdin/stdout
                    ▼
              scripts/tts_worker.py  (D:\vd-ai\venv — torch/CUDA)
                    │  1. Chatterbox Multilingual  → Arabic audio
                    │  2. WhisperX forced-align audio ↔ known text → word times
                    │  3. word times → ElevenLabs-shaped char alignment
                    ▼
              (mp3 bytes, alignment) → timing.json → captions (Pillow+raqm)
```

- **Open TTS returns no timestamps**, so the worker recovers them with
  **WhisperX forced alignment** (the Arabic `wav2vec2-large-xlsr-53-arabic`
  aligner) against the *known* spoken text — word count is preserved, so no
  guessing. Word→char expansion + matching live in `pipeline/wordtiming.py`
  (shared with `pipeline/align.py`).
- The torch/CUDA stack lives in a **separate venv** so the pipeline venv stays
  torch-free and green. The worker is a **persistent subprocess** — models load
  once per `voice.run`, then every scene reuses them.
- Arabic text crosses the process boundary as UTF-8 on a pipe, never a shell
  argv (CLAUDE.md hard rule 4). Worker logs go to `D:\vd-ai\worker.log`
  (never a pipe — a pipe that filled would deadlock generation).

## Build the GPU venv (one time)

Requires an NVIDIA GPU + recent driver, `uv`, and disk for models (~5 GB on
`D:` here). CUDA `cu124` wheels suit Ampere (sm_86); pick the build matching
your GPU/driver.

```powershell
uv venv D:\vd-ai\venv --python 3.12
uv pip install --python D:\vd-ai\venv\Scripts\python.exe --torch-backend=cu124 `
    torch torchaudio chatterbox-tts whisperx
# ctranslate2 (via whisperx) imports pkg_resources, which setuptools >=81 drops:
uv pip install --python D:\vd-ai\venv\Scripts\python.exe "setuptools<81"
```

Model weights download on first use to `HF_HOME` (set it to a roomy drive, e.g.
`D:\vd-ai\models`): Chatterbox multilingual (~3 GB) + the Arabic wav2vec2
aligner (~1.2 GB).

Quick self-check:

```powershell
$env:HF_HOME="D:\vd-ai\models"
D:\vd-ai\venv\Scripts\python.exe -c "import torch,whisperx; from chatterbox.mtl_tts import ChatterboxMultilingualTTS as M; print('cuda',torch.cuda.is_available(),'ar',('ar' in M.SUPPORTED_LANGUAGES))"
```

## Enable it

In `config.yaml` (or a project's `project.yaml`):

```yaml
voice:
  provider: "chatterbox"     # was "elevenlabs"
  chatterbox:
    ai_python: 'D:\vd-ai\venv\Scripts\python.exe'   # or env VD_AI_PYTHON
    hf_home:   'D:\vd-ai\models'                     # or env HF_HOME
    language: "ar"
    voice_ref: ""            # optional ~5s reference wav for cloning; "" = default voice
    exaggeration: 0.5        # Chatterbox expressiveness dial
    cfg_weight: 0.5
    seed: 0                  # >0 = reproducible audio (stable voice_cache)
```

Then the normal loop (`run.py process` / `run.py dub`) uses it. No ElevenLabs
key or `voice_id` is needed; `run.py estimate` is meaningless (cost is fixed).
`voice_ref` clones a voice from a short clean sample — otherwise the model's
default multilingual voice is used.

## Performance & footprint (RTX 3060 Ti, 8 GB)

| | Value |
|---|---|
| VRAM | ~3.2 GB (Chatterbox) + ~1.3 GB (aligner); fits 8 GB with headroom |
| Model load (per `voice.run`) | ~45–60 s, once (persistent worker) |
| First-ever generation | slow (minutes: one-time CUDA kernel warmup) |
| Warm generation | ~2× realtime (a 90 s narration ≈ ~3 min total) |

## Quality gate (do this before trusting it in production)

Chatterbox Multilingual *lists* Arabic, but its dialect/prosody fidelity is
unvalidated (docs 02/06 flag this). Before switching the default:

1. Generate a few real scenes and **A/B listen vs ElevenLabs** — naturalness,
   MSA register, numbers/loanwords, no clipped/garbled words.
2. Spot-check caption sync on the rendered video (WhisperX Arabic word
   boundaries on undiacritized text).
3. Keep `provider: elevenlabs` as the quality baseline until it passes.

## Troubleshooting

- **Worker exits early / errors** — read `D:\vd-ai\worker.log` (full stderr).
  The `StageError` message names it.
- **`ModuleNotFoundError: pkg_resources`** — `setuptools>=81` removed it; run
  `uv pip install "setuptools<81"` in the AI venv.
- **CUDA OOM on the aligner** — the worker already falls back to CPU alignment;
  short per-scene audio makes CPU alignment acceptable.
- **First run seems to hang** — it's one-time CUDA kernel compilation; later
  runs are fast. Watch GPU with `nvidia-smi`.
- **Rebuilding `D:\vd-ai\venv`** — re-run the build commands above (including the
  `setuptools<81` line). Model weights in `HF_HOME` are reused.

## Not done here (future)

- Arabic voice **cloning** from a chosen reference clip (wire `voice_ref`).
- A `run.py doctor` check that's provider-aware (today it warns about a missing
  `voice_id` even under `provider: chatterbox`, where it isn't needed).
- Evaluating VoxCPM / other open Arabic TTS behind the same provider seam.
