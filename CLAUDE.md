# Video Factory — engineering guide (read this first)

Self-hosted pipeline: a source video URL → an original, **Arabic, faceless**
video. Orchestrated by Claude Code. The only variable cost is TTS.

This file is auto-loaded into every Claude Code session opened in this
folder; it is the engineering contract. Companion docs:

- **SETUP.md** — set the project up on another machine (clone → venv →
  deps → verify; cross-platform gotchas: Pillow/raqm, ffmpeg discovery).
- **README.md** — how to *operate* it: the per-topic command loop + setup.
- **PLAN.md** — the product design and phased rationale.
- **.claude/skills/video-script/SKILL.md** — the skill that writes each
  Arabic script (the `script` stage; runs inside Claude Code).
- **DUB.md** — the *separate* dub-and-subtitle path (`scripts/dub_*.py`):
  keeps the source picture, overlays Arabic voice + burned captions.
  Deliberately breaks Hard Rule 1 by design; not part of `run.py process`.
- **docs/ai-video/** — a curated knowledge base of the AI-video field
  (generation models, TTS/timestamps, Arabic RTL captions, editing/MCP,
  publishing, self-hosted stack) + upgrade recommendations. A dated
  snapshot; refreshable via the `ai-video-field-research` workflow. Read
  `docs/ai-video/README.md` first — it confirms the current spine is 2026
  best practice and lists the few worthwhile upgrades.

## Current status (2026-08-30)

- **Built and green:** all 8 stages + orchestrator + the video-script
  skill, plus the dub path. `pytest tests/ -q` = **all passing** (226 at
  time of writing), no network or keys needed.
- **Dub path — built, tested, proven (2026-08-30):** the separate
  keep-the-source Arabic re-voice + subtitle workflow (thin `scripts/dub_*.py`
  over tested logic in `pipeline/dub.py`, docs in DUB.md) produced its first
  video (`projects/romeo-juliet-dub`). Drive it with `run.py dub <slug>` /
  `dub-approve <slug>` / `status <project>`; `run.py process` refuses to run
  on a dub project. Its translation gate is enforced (dub_voice will not spend
  without a `.dub_translation_approved` marker).
- **End-to-end hardening (2026-08-30):** ingest falls back across yt-dlp
  player clients (the YouTube 403 signature/PO-token wall — try `android`),
  the ffmpeg fallback is username-agnostic, and small per-project TEXT inputs
  (translations / project.yaml / segments / source pointer) are git-tracked
  (see `.gitignore` whitelist) so a fresh clone can rebuild a project.
- **Operator hardening (2026-08-02):** four offline commands added —
  `doctor` (preflight: toolchain + go-live config), `estimate` (predict
  ElevenLabs characters/$ before spending), `repair-timing` (rebuild
  `timing.json` from the voiceover via `align` when TTS timing drifts), and
  a content-addressed per-scene TTS cache (`voice_cache/`) so re-running
  voice only re-bills changed scenes. `process` now auto-runs `verify_timing`
  after voice and flags caption-sync drift.
- **Verified against reality:** `render` (real ffmpeg; RTL captions checked
  on actual rendered frames) and `ingest` (real yt-dlp + faster-whisper on
  a live YouTube URL, 2026-07-10).
- **Not yet exercised live:** `voice` (ElevenLabs) and `footage`
  (Pexels/Pixabay) — they need paid API keys, so they only run once `.env`
  is filled. Their logic is unit-tested with mocks.
- **To go live, the human must:** fill `.env`, set `voice.voice_id` in
  `config.yaml`, drop a music bed in `assets/music/`, then validate the
  script skill on real URLs (PLAN Phase 1). Auto-posting and the Remotion
  template are deferred **by design** (PLAN 3.6 / Phase 7) — do not build
  them unprompted.

A fresh session normally does **not** need to rebuild anything. Verify with
pytest, then act on the specific request.

## Verify / run

- Tests: `.venv\Scripts\python.exe -m pytest tests/ -q` (from repo root).
- No-keys end-to-end render (synthetic project, real ffmpeg):
  `.venv\Scripts\python.exe tests\make_sample.py` → inspect
  `projects\sample-demo\final.mp4`.
- Operate for real: see **README.md**. CLI verbs (`python run.py <verb>`):
  `new | new-topic | process | approve | redo | batch`, plus operator aids
  `doctor` (readiness check), `estimate <project>` (TTS cost before gate 1),
  `repair-timing <project>` (re-time from the voiceover when captions
  desync). `doctor` never hits the network; run it first on a fresh machine.
- **`run.py process` exits with code 1 whenever it stops at a gate**
  (script-not-written, gate 1, gate 2). That is the *designed pause*, not a
  failure — read the printed message before treating it as an error.

## Pipeline at a glance

Stage order, driven by `run.py process`:

```
ingest → script → [GATE 1] → voice → footage → captions → render → review → [GATE 2] → publish
```

Two entry points (`Project.is_topic_first()` distinguishes them):
**URL-first** (`new`, writes `source_url.txt`) runs the full order above;
**topic-first** (`new-topic`, writes `topic.txt`) has no source video, so
the orchestrator **drops the ingest stage** and the script stage works from
`topic.txt` instead of `transcript.txt`. Everything from `script` onward is
identical.

Every stage reads/writes files in `projects/<slug>/` and is independently
re-runnable (idempotent). The exact per-stage file I/O table lives in the
`pipeline/contract.py` module docstring. The spine is `script.json` (frozen
shape, `validate_script`); `timing.json` (`validate_timing`) is the audio
timeline every downstream stage trusts as truth over `script.json`'s target
seconds.

| Stage    | Module                   | Role |
|----------|--------------------------|------|
| ingest   | `pipeline/ingest.py`     | yt-dlp audio download + faster-whisper transcript |
| script   | `pipeline/script.py`     | thin gate; the real script is written by the `video-script` skill |
| voice    | `pipeline/voice.py`      | ElevenLabs TTS → `voiceover.mp3` + `timing.json` |
| align    | `pipeline/align.py`      | fallback word alignment when TTS timing is bad (`verify_timing` reports drift) |
| footage  | `pipeline/footage.py`    | Pexels→Pixabay clip search/download; flags unmatched scenes |
| captions | `pipeline/captions.py`   | **Pillow+raqm** RTL karaoke PNGs + manifest (see hard rule 3) |
| render   | `pipeline/render_ffmpeg.py` | ffmpeg assemble: cover-crop, overlay captions, duck music, R128 |
| review   | `pipeline/review.py`     | `contact_sheet.html` (human gate 2) |
| publish  | `pipeline/publish.py`    | `post.json` metadata; banned-phrase guard; **never posts** |

## Hard rules

1. **Nothing from the source video enters the output.** `source.mp4` /
   `transcript.txt` are research inputs for the script stage only.
2. **The two human gates are never automated away.** `run.py` stops at
   gate 1 (script read) and gate 2 (contact sheet), never auto-publishes,
   and `redo` / `--force-stage` re-open (revoke) any gate downstream of the
   changed work (`Project.revoke_gate`) so nothing ships unreviewed.
3. **Arabic captions are NEVER rendered through libass / the ffmpeg
   `subtitles` filter.** The ban does not depend on the current ffmpeg build:
   observed Windows builds (gyan, BtbN — verified 2026-07) ship libass without
   HarfBuzz, so it falls back to legacy presentation-form shaping and modern
   fonts (Tajawal/Cairo) render tofu boxes for isolated/final forms — and a
   build's libass capability can change under you. All caption rendering goes
   through `pipeline/captions.py` (Pillow + libraqm = real HarfBuzz shaping,
   verified correct) — the single trusted Arabic shaping path in BOTH the
   faceless pipeline and the dub. `captions.ass` is exported only as a portable
   artifact for humans/CapCut — never burned by libass.
4. **Never pass Arabic text through PowerShell/Bash command strings** — it
   gets mangled by console codepages. Arabic lives in UTF-8 files only;
   scripts read files. Console output stays ASCII.
5. **Idempotent stages.** A stage that finds its outputs already on disk
   returns without redoing work, unless `force=True`.

## Module shape

Every pipeline stage module exposes exactly:

```python
def run(project: Project, cfg: dict, env: dict, *, force: bool = False) -> None
```

- No stage adds parameters to this signature (the orchestrator calls them
  uniformly). `redo` targets specific scenes by *deleting their clips* and
  re-running the standard stages — not via a `scene_ids` kwarg.
- `--force-stage X` re-runs X **and every stage that consumes its output**
  (the data-dependency closure in `run.py` `STAGE_DEPENDENTS`, not the linear
  order), so a forced regen never leaves a stale downstream artifact — e.g.
  forcing `voice` rebuilds captions/render/review but leaves `footage`
  (independent of timing) alone. This is the narration-edit loop: fix a
  scene's `narration_ar`, then `process --force-stage voice`.
- `Project`, file-name constants, validators, `ffmpeg_path()`, config/env
  loaders all come from `pipeline/contract.py`. Import from there only;
  never hardcode project file names or ffmpeg paths. Cross-stage file names
  are contract constants (`CAPTIONS_DIR`, `CAPTIONS_MANIFEST`,
  `FOOTAGE_REPORT`, `RENDER_REPORT`, …).
- Raise `contract.ContractError` for contract violations (bad/missing
  contracted files, missing required keys); raise
  `errors.StageError(stage, message)` for runtime failures (network,
  ffmpeg, provider) the orchestrator should report and continue past in
  batch mode. Malformed JSON/YAML in a contracted file surfaces as
  `ContractError`, never a raw decode traceback.
- No stage talks to another stage's internals — only project files.

## Environment

- Python: `.venv\Scripts\python.exe` (3.12). Installed: yt-dlp,
  faster-whisper, requests, pyyaml, python-dotenv, pillow (**raqm
  enabled** — required for Arabic shaping), fonttools, pytest.
- **Never assume whether ffmpeg is on PATH** (it varies by machine — a
  WinGet/gyan build may well be) — always resolve via
  `contract.ffmpeg_path()` (`ffmpeg` / `ffprobe`). It checks
  `FFMPEG_PATH`/`FFPROBE_PATH`, then PATH, then per-user fallbacks
  (`~/tools/ffmpeg-btbn/*/bin`, the WinGet Gyan build) — globbed, no
  hardcoded username.
- Fonts: `assets/fonts/` (Tajawal static weights + Cairo variable).
  Tajawal-Bold is the caption font. Never rely on system fonts.
- API keys: `.env` (see `.env.example`). Code must degrade with a clear
  `ContractError` when a needed key is missing — never crash with a
  KeyError or send an unauthenticated request.

## External service rules

- ElevenLabs: `POST /v1/text-to-speech/{voice_id}/with-timestamps`,
  per-scene requests with `previous_text`/`next_text` for prosody
  continuity. Character timestamps are grouped into word timings.
  Pronunciation overrides (`pronunciation.json`) are word→respelling,
  applied to the SPOKEN text only; display text keeps the original word,
  and the 1:1 word mapping is asserted so caption timing stays aligned.
- Pexels primary, Pixabay fallback, both behind the `FootageProvider`
  interface in `pipeline/footage.py`. Keyword sets are tried in order; a
  scene with no acceptable match is recorded as flagged in
  `footage_report.json` — never silently filled.
- All HTTP through `requests` with explicit timeouts and basic retry
  (3 attempts, exponential backoff). Subprocesses decode with
  `encoding="utf-8", errors="replace"`. Tests never hit the network.

## Testing

- `tests/test_<module>.py` per module, pytest, no network, no real
  TTS/footage calls (mock `requests`/`yt_dlp`/`faster_whisper`).
  ffmpeg-touching tests may run real ffmpeg on tiny synthetic inputs
  (lavfi) — keep them a few seconds each. `tests/rtl_smoke/` holds the
  Phase-0 shaping evidence (scripts/images), not pytest tests.
- Run: `.venv\Scripts\python.exe -m pytest tests/ -q` from repo root.

## Naming / files

- Scene clip files: `clips/scene_001.mp4` (`scene_{id:03d}.mp4`).
- Caption frames: `captions/cap_0001.png` + `captions/manifest.json`
  (each frame: png, start, end — seconds, absolute in the final timeline).
- Stage reports (footage gaps, render logs, TTS chars): `<stage>_report.json`
  in the project folder (`voice_report.json` records total vs billed chars).
- `voice_cache/` — content-addressed per-scene TTS audio (`<sha1>.mp3` +
  `.json`), keyed on voice settings + spoken + neighbor text. Reused across
  re-runs so unchanged scenes are never re-billed; delete the folder to
  force fresh audio for identical text.
- Human gate markers: `.gate1_script_approved`, `.gate2_review_approved`.
