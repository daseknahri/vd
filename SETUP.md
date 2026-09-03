# Setting up Video Factory on another machine

This project was built on Windows but runs anywhere Python 3.12 + ffmpeg do.
Read order for someone new: **SETUP.md** (this file, get it running) →
**CLAUDE.md** (engineering contract + current status) → **README.md** (daily
operation) → **PLAN.md** (why it's designed this way).

## What travels with the repo, and what doesn't

**Tracked (you get these on clone):** all code, the `video-script` skill
(`.claude/skills/`), `config.yaml`, `.env.example`, `requirements.txt`, and
the Arabic fonts in `assets/fonts/`.

**NOT tracked — recreate locally** (see `.gitignore`):

| Path | How to recreate |
|------|-----------------|
| `.venv/` | rebuild (step 1) |
| `.env` | copy `.env.example`, fill your keys (step 4) |
| `projects/` | created per video by `run.py new` / `new-topic` |
| `assets/music/*` | drop your own royalty-free beds (optional) |

So a fresh clone has the fonts but no keys, no venv, no music.

## Prerequisites

- **Python 3.12** (built and verified with 3.12.6).
- **ffmpeg + ffprobe** — any recent build with `libx264`, `aac`, and the
  standard filters (`overlay`, `concat`, `sidechaincompress`, `loudnorm`,
  and for the dub `drawbox` + `delogo`).
  You do **not** need a special libass/HarfBuzz build: Arabic captions are
  rendered with Pillow, never libass (that is the entire reason
  `pipeline/captions.py` exists — see CLAUDE.md hard rule 3).
- **git**.
- **Node.js** (recommended, for YouTube sources) — yt-dlp uses a JS runtime
  to decipher YouTube signatures. **YouTube sources note:** the default
  yt-dlp client now 403s on many videos (signature / PO-token wall). `ingest.py`
  automatically falls back to `player_client=android` (a ~360p progressive
  stream); for >360p HD, pass cookies to yt-dlp (`--cookies-from-browser
  chrome` with the browser closed, or `--cookies file.txt`).

## 1. Clone + virtualenv + deps

**Windows (PowerShell):**

```powershell
git clone <your-remote> video-factory
cd video-factory
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

**macOS / Linux (bash):**

```bash
git clone <your-remote> video-factory
cd video-factory
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

## 2. The one cross-platform gotcha: Pillow must have raqm

Arabic shaping depends on Pillow being built with **libraqm** (HarfBuzz).
This command MUST print `True`:

```bash
python -c "from PIL import features; print(features.check('raqm'))"
```

- **Windows:** current PyPI Pillow wheels **no longer bundle raqm** — wheels
  `>= 12.2` dropped it entirely, and `11.0`–`12.1` load `libraqm.dll`
  dynamically but a clean machine lacks the DLL. `requirements.txt` therefore
  pins `pillow<12.2`; then run the one-shot helper, which stages a conda-forge
  libraqm DLL closure into the venv and writes a `sitecustomize.py` so every
  venv Python call finds it:
  ```powershell
  .\.venv\Scripts\python.exe scripts\setup_raqm_windows.py
  ```
  It is idempotent (a no-op once raqm works). The DLLs live in `.venv\raqm\`,
  so **rebuilding the venv means re-running this script.** (Older/other machines
  may already print `True` if libraqm is present system-wide from another tool.)
- **Debian/Ubuntu:** install the system libs, then rebuild Pillow from source:
  ```bash
  sudo apt-get install -y libraqm-dev libharfbuzz-dev libfribidi-dev libfreetype-dev
  pip install --force-reinstall --no-binary :all: pillow
  ```
- **macOS (Homebrew):**
  ```bash
  brew install libraqm freetype harfbuzz fribidi
  pip install --force-reinstall --no-binary :all: pillow
  ```

If it prints `False`, captions will render Arabic as disconnected tofu —
do not proceed until it is `True`.

## 3. ffmpeg discovery

`contract.ffmpeg_path()` finds ffmpeg in this order: the `FFMPEG_PATH` /
`FFPROBE_PATH` env vars → PATH → a couple of Windows-only fallback install
paths (harmless elsewhere). On macOS/Linux just put ffmpeg on PATH:

```bash
ffmpeg -version    # should print a version
```

…or point the env vars at it if it lives somewhere unusual:

```bash
export FFMPEG_PATH=/opt/ffmpeg/bin/ffmpeg
export FFPROBE_PATH=/opt/ffmpeg/bin/ffprobe
```

## 4. Config + keys (only needed for a real render)

```bash
cp .env.example .env      # then fill ELEVENLABS_API_KEY, PEXELS_API_KEY
# edit config.yaml -> voice.voice_id  (an Arabic ElevenLabs voice)
# drop one royalty-free .mp3 into assets/music/   (optional)
```

Never commit `.env`, and never paste keys into a chat — put them in the file
(`.env.example` is a template and must always keep its values BLANK).
Without keys you can still run the script stage and the no-keys sample render.

**ElevenLabs key scopes + voice_id.** A key can be *scope-limited*: a
`text_to_speech`-only key runs the whole voice/dub pipeline, but the ElevenLabs
**MCP's voice-browsing** and the `/v1/voices`/`/v1/user` endpoints need
`voices_read` / `user_read` (they return 401 `missing_permissions` otherwise).
If you can't list voices via API, pick a known premade `voice_id` (e.g. George
`JBFqnCBsd6RMkjVDRZzb`) and set it in `config.yaml` or a project's `project.yaml`.

## 5. Verify the install

```bash
# a) unit suite — no keys, no network (expect all passing; 226 at time of writing)
python -m pytest tests/ -q

# b) no-keys end-to-end render (real ffmpeg on a synthetic project)
python tests/make_sample.py
#    -> inspect projects/sample-demo/final.mp4  — RTL captions burned in
```

If both pass, the machine is ready. Then follow **README.md** to make videos
(`run.py new <url>` or `run.py new-topic "<topic>"`).

## Resume on a new machine (checklist)

The repo lives at **https://github.com/daseknahri/vd.git** (branch `master`).
To pick up work on another laptop:

1. **Clone + environment** — steps 1–3 above (clone, venv, `requirements.txt`,
   confirm `raqm` prints `True`, confirm ffmpeg is discoverable).
2. **Secrets** — recreate `.env` from `.env.example` and fill your keys
   (step 4). Keys are gitignored by design, so copy them across by hand — a
   password manager or an encrypted note, never a chat or a commit.
3. **Music (optional)** — drop your royalty-free `.mp3` beds into
   `assets/music/`; none are tracked.
4. **Verify** — run step 5 (`pytest` + the no-keys sample render). If both
   pass, the machine is ready.
5. **In-flight project folders** — media and regenerable JSON under
   `projects/` are gitignored, but the small TEXT inputs now travel with the
   clone (the `.gitignore` whitelist tracks `project.yaml`,
   `dub_translations.json`, `dub_segments*.json`, `source_url.txt`,
   `topic.txt`, `pronunciation.json`). So for a **dub** project you only need
   to re-supply the media by hand — `source.mp4` (re-download; see DUB.md) —
   then re-run `run.py dub projects\<slug>` and the pipeline rebuilds
   `script.json` / `timing.json` / `voiceover.mp3` / captions / `final.mp4`.
   For a normal URL/topic project, `source_url.txt` / `topic.txt` already sync;
   just re-run `run.py process`.

That's it — code, the `video-script` skill, fonts, and all four docs
(CLAUDE / README / SETUP / [DUB.md](DUB.md)) travel with the clone.

### Pushing changes back

```bash
git add -A
git commit -m "..."
git push
```

If someone else (or your other laptop) pushed first, `git pull --rebase`
before pushing. Because `.env`, `.venv/`, `projects/`, and music are
gitignored, they never leave the machine — each clone recreates them per
this file.

## Command translation (Windows ↔ Unix)

| Windows (PowerShell)           | macOS / Linux (bash)        |
|--------------------------------|-----------------------------|
| `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| `.\.venv\Scripts\python.exe`   | `.venv/bin/python`          |
| `projects\<slug>` (backslash)  | `projects/<slug>` (slash)   |

The deeper engineering gotchas (libass ban, `process` exiting 1 at a gate by
design, never putting Arabic in a shell command) live in **CLAUDE.md**.
