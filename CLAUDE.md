# Video Factory — working conventions

Self-hosted pipeline: source video URL → original Arabic faceless video.
PLAN.md is the product contract; this file is the engineering contract.

## Hard rules

1. **Nothing from the source video enters the output.** `source.mp4` /
   `transcript.txt` are research inputs for the script stage only.
2. **The two human gates are never automated away.** `run.py` stops at
   gate 1 (script read) and gate 2 (contact sheet) and never auto-publishes.
3. **Arabic captions are NEVER rendered through libass / the ffmpeg
   `subtitles` filter on Windows.** Windows ffmpeg builds (gyan, BtbN —
   both verified 2026-06) ship libass without HarfBuzz: it falls back to
   legacy presentation-form shaping and modern fonts (Tajawal/Cairo) render
   tofu boxes for isolated/final forms. All caption rendering goes through
   `pipeline/captions.py` (Pillow + libraqm = real HarfBuzz shaping,
   verified correct). `captions.ass` is exported only as a portable
   artifact for humans/CapCut — never burned by libass.
4. **Never pass Arabic text through PowerShell command strings** — it gets
   mangled by console codepages. Arabic lives in UTF-8 files only; scripts
   read files.
5. **Idempotent stages.** A stage that finds its outputs already on disk
   returns without redoing work, unless `force=True`.

## Module shape

Every pipeline stage module exposes:

```python
def run(project: Project, cfg: dict, env: dict, *, force: bool = False) -> None
```

- `Project`, file-name constants, validators, `ffmpeg_path()`, config/env
  loaders all come from `pipeline/contract.py`. Import from there only;
  never hardcode project file names or ffmpeg paths.
- Raise `contract.ContractError` for contract violations; raise
  `StageError(stage, message)` (defined in `pipeline/errors.py`) for
  runtime failures the orchestrator should report and continue past in
  batch mode.
- No stage talks to another stage's internals — only project files.

## Environment

- Python: `.venv\Scripts\python.exe` (3.12). Installed: yt-dlp,
  faster-whisper, requests, pyyaml, python-dotenv, pillow (raqm enabled),
  fonttools, pytest.
- ffmpeg: resolve via `contract.ffmpeg_path()` — never assume PATH.
- Fonts: `assets/fonts/` (Tajawal static weights + Cairo variable).
  Tajawal-Bold is the caption font.
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
- Pexels primary, Pixabay fallback, both behind `FootageProvider`
  interface in `pipeline/footage.py`. Keyword sets are tried in order;
  a scene with no acceptable match is recorded as flagged in
  `footage_report.json` — never silently filled.
- All HTTP through `requests` with explicit timeouts and basic retry
  (3 attempts, exponential backoff). Unit tests mock HTTP — tests never
  hit the network.

## Testing

- `tests/test_<module>.py` per module, pytest, no network, no real
  TTS/footage calls. ffmpeg-touching tests may run real ffmpeg on tiny
  synthetic inputs (lavfi) — keep them under ~5s each.
- Run: `.venv\Scripts\python.exe -m pytest tests/ -x -q` from repo root.

## Naming / files

- Scene clip files: `clips/scene_001.mp4` (`scene_{id:03d}.mp4`).
- Caption frames: `captions/cap_0001.png` + `captions/manifest.json`
  (entries: png, start, end — seconds, absolute in final timeline).
- Stage reports (footage gaps, render logs): `<stage>_report.json` in the
  project folder.
