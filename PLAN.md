# Video Factory — Complete Build Plan

A self-hosted pipeline that turns a source video URL into an original, Arabic, faceless video ready to publish. Orchestrated by Claude Code. Fixed-cost-first: the only recurring variable cost is text-to-speech.

---

## 1. Guiding principles

These decisions shape everything downstream. Read them before building.

1. **Idea, not asset.** The source video is research only. Nothing from the original file (footage, audio, voice) ever appears in the output. This is both an ethical/legal line and the thing that keeps the channel monetizable under Meta's originality rules.
2. **Fixed cost over variable cost.** Claude (Max plan), Whisper, FFmpeg, Pexels are all free/flat. Only ElevenLabs scales with volume. Every design choice should preserve this.
3. **Two human gates, never skipped.** Script read (language/culture) and final glance (visual match). Everything between them is automated. These two checks are the entire defense against "AI slop."
4. **State on disk, idempotent stages.** Every stage reads and writes a project folder. Any stage can be re-run alone without redoing the others. A crash never costs more than one stage.
5. **Build thin, then thicken.** Get one ugly video end-to-end before polishing any single stage. A working ugly pipeline teaches more than a perfect half-pipeline.
6. **The template is the product.** What makes 100 videos feel like one brand is a fixed visual template. Most one-time creative effort goes here; per-video effort stays near zero.

---

## 2. System architecture

```
video-factory/
├── .claude/
│   └── skills/
│       └── video-script/SKILL.md     # Arabic script format + voice rules
├── config.yaml                       # voice id, aspect ratio, caption style, music
├── .env                              # API keys (gitignored)
├── pipeline/
│   ├── ingest.py        # yt-dlp download + Whisper transcribe
│   ├── script.py        # (thin wrapper; real work done by Claude Code)
│   ├── voice.py         # ElevenLabs TTS + timing extraction
│   ├── align.py         # WhisperX fallback alignment
│   ├── footage.py       # Pexels/Pixabay search + download + filter
│   ├── render_ffmpeg.py # assembly path A
│   ├── render_remotion/ # assembly path B (React template)
│   ├── review.py        # contact sheet generator
│   └── publish.py       # title/description/hashtags (Claude) + optional API post
├── assets/
│   ├── fonts/           # Cairo / Tajawal (Arabic), tested for RTL
│   ├── music/           # royalty-free beds
│   └── brand/           # intro logo, lower-thirds
├── projects/
│   └── YYYY-MM-DD-slug/
│       ├── source_url.txt
│       ├── transcript.txt
│       ├── script.json
│       ├── voiceover.mp3
│       ├── timing.json
│       ├── clips/
│       ├── captions.ass
│       ├── contact_sheet.html
│       └── final.mp4
└── run.py                            # orchestrator: URL -> final.mp4
```

**Data contract between stages** (this is what keeps stages independent):

| Stage | Reads | Writes |
|-------|-------|--------|
| Ingest | `source_url.txt` | `transcript.txt` |
| Script | `transcript.txt` | `script.json` |
| Voice | `script.json` | `voiceover.mp3`, `timing.json` |
| Footage | `script.json` | `clips/*.mp4` |
| Render | all above | `captions.ass`, `final.mp4` |
| Review | `script.json`, `clips/` | `contact_sheet.html` |
| Publish | `script.json` | post metadata |

`script.json` is the spine. Define it once and freeze the shape:

```json
{
  "meta": { "source_url": "...", "audience": "general Arab", "dialect": "MSA", "target_seconds": 90 },
  "hook": "...",
  "scenes": [
    {
      "id": 1,
      "narration_ar": "...",
      "keywords": [["primary terms"], ["fallback 1"], ["fallback 2"]],
      "mood": "archival|energetic|calm",
      "target_seconds": 8
    }
  ],
  "post": { "title": "", "description": "", "hashtags": [] }
}
```

---

## 3. Problems we will hit, and how each is solved

This is the part that matters most. Each is a real failure mode, with a designed-in answer.

### 3.1 Content / legal / policy

- **Re-upload detection (LOC flag).** Risk: output too close to source = demonetized. *Solution:* originality is enforced at the script stage — Claude rewrites from the extracted idea, never paraphrases the transcript sentence-by-sentence. Different structure, different examples, localized references. No source footage or audio ever used.
- **AI-content disclosure.** Meta requires labeling photorealistic AI-generated video and detects provenance via watermark/metadata. *Solution:* default to stock footage (not AI-generated), so disclosure mostly doesn't apply. When AI B-roll is used, label it. Keep this a config flag per project.
- **Music rights.** Copyrighted music = demonetization. *Solution:* music beds come only from a vetted royalty-free folder (`assets/music/`) or Meta's licensed library. Never pull audio from source.
- **Engagement bait.** "Like and share!" language is penalized. *Solution:* bake a banned-phrase list into the script skill, same mechanism as your Kepoli forbidden-words rule.

### 3.2 Arabic-specific technical

- **RTL + letter shaping breakage.** The single biggest technical risk. Wrong font or shaping config = disconnected letters or reversed text. *Solution:* solve once in the template using Cairo/Tajawal fonts; for FFmpeg use libass with a proper Arabic-shaping build; for Remotion use `direction: rtl` + CSS. **Test this on day one** with Claude inspecting a rendered frame before building anything else.
- **TTS mispronunciation.** ElevenLabs occasionally misreads Arabic words, numbers, or foreign names. *Solution:* a per-project pronunciation-override map; respell tricky words phonetically in the narration sent to TTS (keep display text separate from spoken text if needed).
- **Dialect consistency.** Mixing MSA and dialect sounds amateur. *Solution:* dialect is a `meta` field; the skill enforces one register throughout; the Stage-2 human read catches slips.
- **Caption-to-speech sync in RTL.** Karaoke captions must highlight the right word in right-to-left order. *Solution:* drive captions from word-level timing (WhisperX), not estimation; verify on a frame.

### 3.3 Footage matching

- **Wrong stock result** (the "jaguar = car not animal" problem). *Solution:* Claude writes 2–3 fallback keyword sets per scene with the visual literally described; pipeline tries them in order; unmatched scenes are flagged, not silently filled.
- **Repetitive / generic clips** across videos. *Solution:* maintain a per-channel used-clip log; footage stage avoids recently used clip IDs. Mix in motion graphics for abstract scenes that stock can't serve.
- **Orientation / resolution / length mismatch.** *Solution:* filter API results by orientation, min 1080p, duration >= scene length; auto-split long scenes into two clips for rhythm.
- **API rate limits / quota.** Pexels and Pixabay both have free limits. *Solution:* cache downloads, dedupe, and keep both providers wired so one can back up the other.

### 3.4 Timing / assembly

- **Voice/clip drift** (clips don't line up with narration). *Solution:* timing is derived from the actual generated audio, never assumed. Scene boundaries come from `timing.json`.
- **Audio levels** (music drowns voice). *Solution:* sidechain compression ducks music under speech; fixed loudness normalization (EBU R128) so every video sounds consistent.
- **Render failures mid-batch.** *Solution:* idempotent stages + per-project state means a failed render re-runs alone. Batch orchestrator continues other projects and reports failures at the end.

### 3.5 Operational / scaling

- **Quality drift at volume.** More videos, less attention, slop creeps in. *Solution:* the two human gates are mandatory in the orchestrator — the pipeline pauses and will not auto-publish. Volume scales the automated middle, never the judgment.
- **Whisper/render compute.** Local transcription and rendering need CPU/GPU time. *Solution:* faster-whisper (efficient) ; render overnight in batch; this is time, not money.
- **Cost creep.** *Solution:* ElevenLabs is the only meter running. Track characters-per-video; if volume grows, evaluate self-hosted TTS (e.g. XTTS) as the eventual zero-variable-cost endgame.
- **Single point of failure on one provider.** *Solution:* abstract each external service behind a thin interface (voice, footage) so swapping ElevenLabs → another TTS, or Pexels → Pixabay, is a config change, not a rewrite.

### 3.6 Strategic

- **Building before validating format.** Risk: perfect pipeline, wrong content. *Solution:* the phased plan (section 5) forces manual validation of script + format before automating assembly.
- **Over-automating publishing too early.** *Solution:* manual posting for the first months; you learn what lands and feed it back into the skill. Automate posting only once the format is proven.

---

## 4. Tech stack (concrete choices)

- **Orchestration:** Claude Code (Max plan) + Python `run.py`.
- **Download:** yt-dlp.
- **Transcribe:** faster-whisper (local). WhisperX for word-level alignment + captions.
- **Script:** Claude, via the `video-script` skill.
- **TTS:** ElevenLabs API (`/with-timestamps`). Interface abstracted for future swap.
- **Footage:** Pexels API primary, Pixabay fallback. Both free.
- **Assembly:** FFmpeg first (libass captions, sidechain audio). Remotion later for branded polish.
- **Fonts:** Cairo / Tajawal (verified RTL).
- **Config:** `config.yaml` + `.env` for keys.
- **Version control:** git; `.env`, `projects/`, and `clips/` gitignored.

---

## 5. Phased build order

Each phase ends with something usable. Do not skip ahead.

### Phase 0 — Foundation (½ day)
- Repo scaffold, config, `.env`, git.
- Install yt-dlp, faster-whisper, FFmpeg.
- **RTL smoke test:** render one frame of Arabic text with the chosen font; Claude inspects it. Nothing proceeds until letters connect and read right-to-left correctly.
- *Output:* proof the hardest technical risk is solved.

### Phase 1 — Idea → script (1 day)
- Build ingest (download + transcribe).
- Write the `video-script` skill: HOOK, scenes, keywords, banned words, dialect, format. Mirror your Kepoli skill discipline.
- *Validation:* run 5 real source URLs → 5 Arabic scripts. **You read them.** Iterate the skill until script quality is reliably good. *Test these scripts manually in CapCut to confirm the format works before automating the rest.*
- *Output:* trustworthy scripts. This is the most important phase — everything downstream is plumbing.

### Phase 2 — Voice (½ day)
- ElevenLabs integration, timestamps → `timing.json`.
- Pronunciation-override mechanism.
- WhisperX alignment fallback.
- *Output:* voiceover + accurate per-scene timing.

### Phase 3 — Assembly, minimal (1 day)
- FFmpeg render: trim, scale/crop to aspect ratio, concat, burn captions, mix one music bed with ducking, loudness-normalize.
- Manual footage at first (drop any clips in `clips/`) to test render in isolation.
- Claude self-checks frames (RTL captions, stretching).
- *Output:* first complete ugly video, end to end.

### Phase 4 — Footage automation (1 day)
- Pexels search with fallback keyword sets, filtering, download, used-clip log, Pixabay backup.
- *Output:* the URL → near-final video path closes.

### Phase 5 — Review gate + publish prep (½ day)
- `contact_sheet.html`: thumbnail per scene next to narration; "redo scene N" loop re-fetches and re-renders only those scenes.
- Claude writes title/description/hashtags.
- *Output:* the full loop, with the human glance built in.

### Phase 6 — Orchestration + batch (½ day)
- `run.py`: single URL runs Phases 1→5, pausing at the two gates.
- Batch mode: list of URLs, parallel processing, failure report.
- *Output:* "make videos from these 10 URLs" → 10 drafts to review.

### Phase 7 — Polish (ongoing, optional)
- Remotion template for branded captions/intro/animation.
- Motion-graphics scenes for abstract content.
- Later: AI B-roll (labeled), auto-posting via Meta API, self-hosted TTS to zero out variable cost.

---

## 6. The two skills to write carefully

1. **`video-script`** — the heart. Inputs: transcript + audience/dialect. Output: `script.json`. Encodes hook rules, scene segmentation, English keyword generation with fallbacks, banned filler/engagement-bait words, dialect register, target length. Treat it with the same rigor as your Kepoli recipe skill.
2. **Footage-keyword discipline** (can live inside the script skill) — the rule that keywords describe the literal visual ("aerial desert highway sunset"), not the abstract idea ("journey"), with concrete fallbacks. Match quality lives or dies here.

---

## 7. Definition of done (per video)

A video is publish-ready when:
- Script read and approved (human gate 1).
- Voice clean, no mispronunciations.
- Every scene has a matching clip; no flagged gaps.
- Captions sync correctly and render RTL-correct.
- Audio normalized, music ducked.
- Contact sheet glanced and approved (human gate 2).
- Title/description/hashtags generated, no banned phrases.
- Runtime ≥ 3 min if targeting in-stream ads; Reels cut available for reach.

---

## 8. Economics

- **Fixed (already paid):** Claude Max, your machine.
- **Variable per video:** ElevenLabs only, ~$0.10–0.30.
- **Free:** Whisper, FFmpeg, Pexels, Pixabay, fonts, music.
- **Endgame:** swap ElevenLabs → self-hosted TTS to reach ~$0 marginal cost once volume justifies it.

Per-video human time at steady state: ~5 minutes (paste URL, read script, glance, post).

---

## 9. First three actions

1. Build Phase 0 and pass the RTL smoke test.
2. Write the `video-script` skill and validate on 5 real URLs.
3. Manually assemble one of those scripts in CapCut to confirm the format lands before automating assembly.

Everything else follows from a good script and a correct RTL render. Nail those two and the pipeline is mostly plumbing.
