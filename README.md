# Video Factory

Self-hosted pipeline: a source video URL becomes an **original, Arabic,
faceless video** ready to publish. Orchestrated by Claude Code. The only
recurring variable cost is text-to-speech.

Read [PLAN.md](PLAN.md) for the full design and
[CLAUDE.md](CLAUDE.md) for engineering conventions (including why Arabic
captions are rendered with Pillow+raqm instead of libass on Windows).

## One-time setup

1. `copy .env.example .env` and fill in `ELEVENLABS_API_KEY`,
   `PEXELS_API_KEY` (and optionally `PIXABAY_API_KEY`).
2. Set `voice.voice_id` in `config.yaml` (an ElevenLabs Arabic voice).
3. Drop at least one royalty-free music bed into `assets/music/`
   (optional — videos render voice-only without it).

## Per-video flow (~5 minutes of your time)

```text
python run.py new <source-url>          # creates projects/YYYY-MM-DD-slug/
python run.py process projects/<slug>   # ingest + transcribe, then stops:
                                        #   -> write the script with the
                                        #      video-script skill in Claude Code
python run.py process projects/<slug>   # stops at GATE 1
# read projects/<slug>/script.json — the language/culture check
python run.py approve projects/<slug> --gate 1
python run.py process projects/<slug>   # voice -> footage -> captions ->
                                        # render -> contact sheet, stops at GATE 2
# open projects/<slug>/contact_sheet.html — the visual check
python run.py redo projects/<slug> --scenes 3 5   # if a scene's clip is wrong
python run.py approve projects/<slug> --gate 2
python run.py process projects/<slug>   # writes post.json; publishing is manual
```

Batch: `python run.py batch urls.txt` — every project advances to its
next human gate; failures are collected and reported at the end.

## The two human gates

1. **Script read** — you read `script.json` before any money is spent on
   TTS. Language, culture, originality.
2. **Contact sheet glance** — `contact_sheet.html` shows every scene's
   clip thumbnail next to its narration. Visual match, flagged gaps.

The pipeline never skips them and never auto-posts.
