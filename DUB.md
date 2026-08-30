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

**Fastest path — the dispatcher.** `run.py dub <project-dir>` advances the
project to its next step from what's on disk: it runs the automatable steps
(segment, build, captions, voice-after-approval, render) and STOPS with
instructions at the manual ones (write translations, approve). It never folds
the dub into `run.py process` — `process` refuses to run on a dub project.

```bash
.venv\Scripts\python.exe run.py dub projects\<slug>          # run until the next manual step
.venv\Scripts\python.exe run.py dub-approve projects\<slug>  # record the translation-review approval
.venv\Scripts\python.exe run.py status projects\<slug>       # which outputs exist
```

The individual scripts below are the granular manual path (what the dispatcher
calls); use them to re-run a single step.

| Step | Command | Reads → Writes |
|------|---------|----------------|
| 1. Segment | `scripts\dub_segment.py <slug> [--marker "phrase"]` | `source.mp4` → `dub_segments.json` (whisper word-timing, story window, caption-sized EN sentences). Story-end marker: `--marker` or `project.yaml dub.story_end_marker`; warns loudly if it doesn't match. |
| 1b. Refine | `scripts\dub_refine_segments.py <slug> <first> <last>` | `dub_segments.json` → `dub_segments.refined.json` (**non-destructive** — raw kept; downstream prefers the refined file). Merges fragments into whole sentences over the story id-range `[first..last]`. |
| — Translate | *(hand-edit)* `dub_translations.json` | one faithful Arabic (MSA) line per segment id, **plus** a `post` object (title/description/hashtags) and a `source_url` (or add `source_url.txt`) — required; nothing about a specific video is hardcoded. |
| 2. Build script | `scripts\dub_build_script.py <slug>` | segments + `dub_translations.json` → `script.json` (each scene's `target_seconds` = its source-video slot; `meta.workflow="dub"`) |
| — Review gate | `scripts\dub_review.py <slug>` | `script.json` → `dub_review.html` (EN↔AR table + ElevenLabs char/cost estimate, rate from config). **Vet before spending, then `run.py dub-approve`.** |
| 3. Voice | `scripts\dub_voice.py <slug> [--force]` | `script.json` → `voiceover.mp3` + `timing.json`. Places each Arabic clip at its **source timestamp**, atempo-fits into the gap ahead (cap ~1.30×), pushes later scenes only past the cap. **Refuses to spend without the `.dub_translation_approved` marker** (`run.py dub-approve`). |
| 4. Captions | `run.py dub <project-dir>` runs it, or call `pipeline.captions.run(project, cfg, env)` | `script.json` + `timing.json` → `captions/` PNGs + manifest (Pillow+raqm) |
| 5. Render | `scripts\dub_render.py <slug> [--force]` | source (muted, scaled/padded, subtitles covered, watermark erased) + `voiceover.mp3` + burned captions → `final.mp4` |

Example (granular, `romeo-juliet-dub`):

```bash
.venv\Scripts\python.exe scripts\dub_segment.py romeo-juliet-dub
.venv\Scripts\python.exe scripts\dub_refine_segments.py romeo-juliet-dub 2 56
# edit projects\romeo-juliet-dub\dub_translations.json (Arabic + post + source_url)
.venv\Scripts\python.exe scripts\dub_build_script.py romeo-juliet-dub
.venv\Scripts\python.exe scripts\dub_review.py romeo-juliet-dub
.venv\Scripts\python.exe run.py dub-approve projects\romeo-juliet-dub   # after vetting dub_review.html
.venv\Scripts\python.exe run.py dub projects\romeo-juliet-dub           # voice -> captions -> render
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

Most of `projects/` is gitignored, but the small TEXT inputs a dub needs to be
rebuilt **are** tracked (see the `.gitignore` whitelist): `project.yaml`,
`dub_translations.json`, `dub_segments.json` / `.refined.json`, and
`source_url.txt`. So on a fresh clone you only re-supply the media —
`source.mp4` (re-download; see below) — and re-run from `dub_build_script`
(or `run.py dub`). Regenerable artifacts (`script.json`, `timing.json`,
`voiceover.mp3`, captions, `final.mp4`, `voice_cache/`) stay ignored and
rebuild from the tracked inputs.

## Going live (same prerequisites as the main pipeline)

The voice step needs `ELEVENLABS_API_KEY` in `.env` and an Arabic `voice_id`
in config. Use `dub_review.py`'s estimate and `dub_dryrun.py` to verify
everything offline first, then run `dub_voice.py`.

## Downloading the source (this Windows machine)

YouTube's default DASH path 403s here (signature deciphering needs a JS
runtime; the `web` client needs a PO token; cookie extraction fails on
app-bound encryption). Reliable fallback for a progressive mp4:

```bash
.venv\Scripts\python.exe -m yt_dlp --extractor-args "youtube:player_client=android" ^
  -f 18 -o "projects\<slug>\source.mp4" <url>
```

(Format 18 is a single progressive stream, so no ffmpeg merge is needed. For
>360p HD, close the browser and add `--cookies-from-browser chrome`, or pass a
`--cookies cookies.txt` file. The main pipeline's `ingest.py` now applies this
`android` fallback automatically.)

`-f 18` yields 360p (audio+video, no signature needed). For >360p, close
Chrome fully and retry `--cookies-from-browser chrome`, or export cookies to a
file and pass `--cookies`.

## First project

`projects/romeo-juliet-dub/` — story-only (0:00–4:40, ~40 sentences, ~264s) of
a Romeo & Juliet slow-English YouTube video, faithful MSA translation timed to
scenes, original English audio fully muted, rendered at 1280×720. The
story/teaching boundary was set manually (`dub_refine_segments … 2 56`) because
the whisper marker match failed on the contraction "let's".
