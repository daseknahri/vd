# Video Factory

Self-hosted pipeline: a source video URL becomes an **original, Arabic,
faceless video** ready to publish. Orchestrated by Claude Code. The only
recurring variable cost is text-to-speech.

Read [PLAN.md](PLAN.md) for the full design and
[CLAUDE.md](CLAUDE.md) for engineering conventions (including why Arabic
captions are rendered with Pillow+raqm instead of libass on Windows).

## Where you do the work

One place: a **Claude Code session opened inside this folder**
(`C:\Users\user\video-factory`). The script-writing step only works inside
Claude Code (the `video-script` skill lives there), so the simplest habit is
to run everything from there — it executes the commands below *and* writes
the Arabic script. You only step in at the two human gates.

```powershell
cd C:\Users\user\video-factory
.\.venv\Scripts\Activate.ps1     # switch on the project's Python (once per terminal)
claude                           # start Claude Code here, then just say what you want
```

After activating the venv, `python` means the project's Python. If you skip
activation, prefix every command with `.\.venv\Scripts\python.exe` instead
of `python`.

## One-time setup

1. `copy .env.example .env` and fill in `ELEVENLABS_API_KEY`,
   `PEXELS_API_KEY` (and optionally `PIXABAY_API_KEY`).
2. Set `voice.voice_id` in `config.yaml` (an ElevenLabs Arabic voice).
3. Drop at least one royalty-free music bed into `assets/music/`
   (optional — videos render voice-only without it).

## One video per topic — the loop you repeat every time

Each topic becomes its **own dated folder** under `projects\`; topics never
collide. Same six steps every time — only the URL changes:

```text
python run.py new <URL-for-this-topic>       # 1. creates projects\YYYY-MM-DD-slug\
python run.py process projects\<slug>        # 2. download + transcribe, then STOPS
      # -> in Claude Code: write the script (video-script skill fills script.json)
python run.py approve projects\<slug> --gate 1   # 3. after you READ script.json
python run.py process projects\<slug>        # 4. voice -> footage -> captions ->
                                             #    render, then STOPS at gate 2
      # -> open projects\<slug>\contact_sheet.html and look
python run.py redo projects\<slug> --scenes 3 5  #    (only if a clip is wrong)
python run.py approve projects\<slug> --gate 2   # 5. after you GLANCE
python run.py process projects\<slug>        # 6. writes post.json; final.mp4 is ready
```

**Next topic = start again at step 1 with a new URL.** There is nothing to
re-set-up; the folders keep every topic separate.

Note: `process` prints instructions and **exits with code 1 whenever it stops
at a gate** — that is the designed pause, not an error.

Many topics at once:
`python run.py batch urls.txt` — one URL per line; every project advances to
its next human gate and failures are reported at the end.

## The two human gates

1. **Script read** — you read `script.json` before any money is spent on
   TTS. Language, culture, originality.
2. **Contact sheet glance** — `contact_sheet.html` shows every scene's
   clip thumbnail next to its narration. Visual match, flagged gaps.

The pipeline never skips them and never auto-posts.
