# Dub workflow — keep-the-source Arabic re-voice + subtitle path

A **second, separate** workflow that lives beside the main faceless-original
`process` pipeline. It **keeps the source video's picture**, mutes its audio,
lays an Arabic ElevenLabs voiceover on top, and burns Arabic captions.

This deliberately breaks **Hard Rule 1** in [CLAUDE.md](CLAUDE.md) ("nothing
from the source enters the output"). That is by design and by explicit request
— which is exactly why it is a *separate* set of scripts under `scripts/`, not
a mode of `run.py process`. Do not fold it into the main pipeline.

## Why it stays clean

It reuses the existing spine rather than forking it:

- It emits a standard, contract-valid `script.json` (`validate_script`) and
  `timing.json` (`validate_timing`), so `pipeline/captions.py` (Pillow + raqm
  RTL karaoke) and `render_ffmpeg`'s caption-track builder work unchanged.
- **Hard Rule 3 still holds** — Arabic is shaped only through the Pillow+raqm
  PNG frames; libass is never used.
- It reuses `pipeline.voice.ElevenLabsTTS` and the content-addressed
  `voice_cache/`, so re-runs never re-bill unchanged scenes.

The dub scripts are intentionally thin wiring (not `run.py` stages) until the
format is proven — see "don't over-engineer" in the global instructions.

## Pipeline order

All commands run from the repo root with the venv Python. `<slug>` is the
project folder name under `projects/` (default in most scripts:
`romeo-juliet-dub`).

```
dub_segment → dub_refine_segments → [edit dub_translations.json]
  → dub_build_script → dub_review → [GATE: approve translation]
  → dub_voice → captions stage → dub_render
```

| Step | Command | Reads → Writes |
|------|---------|----------------|
| 1. Segment | `scripts\dub_segment.py <slug>` | `source.mp4` → `dub_segments.json` (whisper word-timing, story window, caption-sized EN sentences) |
| 1b. Refine | `scripts\dub_refine_segments.py <slug> <first> <last>` | merges whisper fragments into whole sentences, trims to story window `[first..last]`, renumbers |
| — Translate | *(hand-edit)* `dub_translations.json` | one faithful Arabic (MSA) line per segment id |
| 2. Build script | `scripts\dub_build_script.py <slug>` | `dub_segments.json` + `dub_translations.json` → `script.json` (each scene's `target_seconds` = its source-video slot) |
| — Review gate | `scripts\dub_review.py <slug>` | `script.json` → `dub_review.html` (EN↔AR table + ElevenLabs char/cost estimate). **Vet before spending.** |
| 3. Voice | `scripts\dub_voice.py <slug> [--force]` | `script.json` → `voiceover.mp3` + `timing.json`. Places each Arabic clip at its **source timestamp**, atempo-fits into the gap ahead (cap ~1.30×), only pushes later scenes when the cap isn't enough. |
| 4. Captions | run the normal captions stage | `script.json` + `timing.json` → `captions/` PNGs + manifest |
| 5. Render | `scripts\dub_render.py <slug> [--force]` | source (muted, scaled/padded to canvas) + `voiceover.mp3` + burned captions → `final.mp4` |

Example (full):

```bash
.venv\Scripts\python.exe scripts\dub_segment.py romeo-juliet-dub
.venv\Scripts\python.exe scripts\dub_refine_segments.py romeo-juliet-dub 2 56
# edit projects\romeo-juliet-dub\dub_translations.json
.venv\Scripts\python.exe scripts\dub_build_script.py romeo-juliet-dub
.venv\Scripts\python.exe scripts\dub_review.py romeo-juliet-dub
# ...approve dub_review.html...
.venv\Scripts\python.exe scripts\dub_voice.py romeo-juliet-dub
# ...run captions stage...
.venv\Scripts\python.exe scripts\dub_render.py romeo-juliet-dub
```

## Zero-cost dry run

`scripts\dub_dryrun.py <slug>` builds a synthetic `timing.json` (each scene in
its source slot) and a silent `voiceover.mp3`, so you can verify Arabic caption
shaping/placement on real rendered frames and the whole assembly path **before
spending any ElevenLabs characters**. The real `dub_voice.py` then overwrites
both files with billed audio + exact word timings.

```bash
.venv\Scripts\python.exe scripts\dub_dryrun.py <slug>
# ...run captions stage, then:
.venv\Scripts\python.exe scripts\dub_render.py <slug>
```

## Per-project config (`projects/<slug>/project.yaml`)

The dub path reads an optional per-project `project.yaml` that overrides global
`config.yaml` — e.g. switch the global 9:16 to 16:9 `1280×720`, and configure
source cleanup:

- **`dub.cover_top` / `dub.cover_bottom`** — a floating opaque band that hides
  burned-in source subtitles (the original's own lower-third) while still
  showing the scene above/below it.
- **`dub.watermark`** — a `delogo` box (`x1/y1/w/h`) that erases a channel
  watermark. Note: `delogo` leaves a faint smudge on textured backgrounds —
  acceptable, not perfect.

`projects/` is gitignored, so these per-project files do **not** sync via git.
Recreate `project.yaml`, `dub_translations.json`, and `source.mp4` on the other
machine (or copy the project folder manually).

## Going live (same prerequisites as the main pipeline)

The voice step needs `ELEVENLABS_API_KEY` in `.env` and an Arabic `voice_id`
in config. Use `dub_review.py`'s estimate and `dub_dryrun.py` to verify
everything offline first, then run `dub_voice.py`.

## Downloading the source (this Windows machine)

YouTube's default DASH path 403s here (signature deciphering needs a JS
runtime; the `web` client needs a PO token; cookie extraction fails on
app-bound encryption). Reliable fallback for a progressive mp4:

```bash
.venv\Scripts\python.exe -m yt_dlp --extractor-args "youtube:player_client=android" -f 18 \
  --ffmpeg-location "C:/Users/user/tools/ffmpeg-btbn/ffmpeg-n8.1-latest-win64-gpl-8.1/bin" <url>
```

`-f 18` yields 360p (audio+video, no signature needed). For >360p, close
Chrome fully and retry `--cookies-from-browser chrome`, or export cookies to a
file and pass `--cookies`.

## First project

`projects/romeo-juliet-dub/` — story-only (0:00–4:40, ~40 sentences, ~264s) of
a Romeo & Juliet slow-English YouTube video, faithful MSA translation timed to
scenes, original English audio fully muted, rendered at 1280×720. The
story/teaching boundary was set manually (`dub_refine_segments … 2 56`) because
the whisper marker match failed on the contraction "let's".
