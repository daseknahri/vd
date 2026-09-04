---
name: video-script
description: >
  Turn a source-video transcript into an original Arabic faceless-video
  script (script.json) for the video-factory pipeline. Use whenever a
  project folder has transcript.txt and needs script.json, or the user asks
  for a video script / "اكتب سكربت". Enforces originality (idea, not
  paraphrase), one dialect register, literal-visual stock keywords, banned
  engagement-bait, and the frozen script.json contract.
---

# video-script — transcript → original Arabic script

You are writing the **single most important artifact** in this pipeline.
Everything downstream (voice, footage, captions, render) is plumbing; the
script is the product. A human reads the result at gate 1 — write so that
the read is a pleasure, not a correction session.

## Inputs

A project is one of two modes — detect by which file is present:

- **URL-first** — `projects/<slug>/transcript.txt` exists: transcript of
  the SOURCE video, research material only. Apply the originality rule
  below in full.
- **Topic-first** — `projects/<slug>/topic.txt` exists (no transcript):
  a single line naming the topic. There is no source to rewrite, so the
  script is original by construction — but you still own the angle, the
  facts, and the localization. Invent a strong, specific take on the topic
  rather than a generic listicle; verify every fact; localize examples.

Then, common to both:

- Defaults from `config.yaml` → `script.audience`, `script.dialect`,
  `video.target_seconds` (overridable per project via `project.yaml`
  or explicit user instruction).

## The originality rule (non-negotiable)

The transcript is **an idea quarry, not a text to translate**.

- Read the whole transcript. Extract: the core idea (one sentence), the
  3–6 strongest facts/claims, and what made it work as a video.
- Close the quarry. Build a NEW outline with a different structure:
  different opening angle, different ordering, different examples.
- Localize: examples, analogies, names and numbers an Arab viewer feels
  at home with (replace a US-suburb anecdote with a Cairo/Riyadh/Casablanca
  one; convert units; use regionally famous references).
- NEVER paraphrase sentence-by-sentence. If a scene of yours can be lined
  up 1:1 against a transcript paragraph, rewrite it.
- Verify any fact you keep. Drop claims you cannot stand behind; never
  invent statistics. If the source's central claim is dubious, say so in
  the script honestly or pick a defensible angle.

## Script architecture

- **Hook (first scene, ≤ 3 seconds of speech):** the `hook` field holds the
  hook line, and scene 1's `narration_ar` MUST open with that exact line —
  the voice stage only reads scenes, so a hook that lives only in the
  `hook` field is never heard. A hook poses a concrete question, a
  surprising number, or a stakes statement. No "في هذا الفيديو سنتعرف على"
  — that phrasing is banned.
- **Scenes:** 6–12 for a 90-second video. One scene = one visual idea =
  5–12 seconds. `target_seconds` per scene; the sum must land within ±10%
  of `meta.target_seconds`.
- **Pacing:** MSA voiceover ≈ 2.2–2.6 words/second. An 8-second scene is
  ~18–20 words. Count words; do not eyeball.
- **Arc:** hook → context (why should I care) → escalation of the idea in
  2–4 beats → payoff/twist → a closing thought that completes the idea
  (NOT a call to action). End when the idea ends.

## Language register

- `meta.dialect` is set once and never mixed. Default `MSA`: modern,
  spoken-flavored فصحى — short sentences, everyday vocabulary, no
  literary stiffness (لا "إنَّ المرءَ لَيَعجبُ"), no bureaucratic filler
  (لا "وتجدر الإشارة إلى أن").
- Write for the EAR: rhythm, repetition used deliberately, questions to
  the viewer. Read each scene aloud mentally.
- TTS-safety:
  - Numbers as Arabic words when short («ثلاثة آلاف» not «3000»);
    4-digit years may stay as digits.
  - Avoid words you know ElevenLabs garbles; prefer the simpler synonym.
  - Foreign names: add a `pronunciation.json` entry mapping the written
    word to a phonetic Arabic respelling, and keep the written form in
    the narration. The map must be word→word (1:1), never word→phrase,
    or caption timing breaks.
- No tashkeel except where ambiguity actually hurts comprehension.

## Banned phrases (engagement bait & filler)

Never in narration, title, description, or hashtags — these get the
channel penalized and mark the content as slop:

اشترك في القناة، فعّل الجرس، لايك، شير، لا تنسَ الاشتراك، اضغط زر
الإعجاب، شاركنا رأيك في التعليقات (as a closing CTA), تابعونا،
"في هذا الفيديو", "سنتعرف اليوم على", "بدون مقدمات",
"like and subscribe", "smash that button", "link in bio".

Genuine rhetorical questions inside the content are fine; manufactured
engagement is not.

## Footage keywords (match quality lives or dies here)

For each scene, `keywords` is a list of 2–3 **fallback sets**, tried in
order by the footage stage. Each set is 1 list of 2–4 ENGLISH words.

- Describe the **literal visual**, not the abstract idea:
  - ❌ `["success", "journey"]`
  - ✅ `["aerial desert highway", "sunset"]` then `["man walking dune"]`
- Imagine the actual stock clip playing behind the words. Name the
  subject + setting (+ camera angle or time of day when it matters).
- Set 1 = ideal shot; set 2 = simpler/more generic version; set 3 =
  safe abstraction that still fits the mood.
- Disambiguate homonyms in-set («jaguar animal rainforest», never bare
  «jaguar»).
- `mood` must be one of `archival | energetic | calm` — pick per scene,
  and let it vary with the arc (hook is rarely `calm`).

## Generated B-roll prompt (optional — only when generating footage locally)

When the channel generates B-roll on the GPU instead of pulling stock
(`footage.ai_broll: true`, see `docs/ai-video/GENERATED_BROLL.md`), each scene
may carry an optional `broll_prompt`: a descriptive English text-to-video prompt
used verbatim by the generator. The video model (LTX-Video) rewards **long,
descriptive** prompts, so the terse `keywords` (perfect for stock search) are
too thin on their own. Write `broll_prompt` for generated-footage channels;
omit it for stock-only projects (the terse keywords still work there).

- One or two vivid English sentences: **subject + setting + camera motion +
  lighting + style** — e.g. *"A slow cinematic aerial push-in over rolling
  desert dunes at golden hour, wind-blown sand, warm low sun, soft haze, smooth
  drone motion, photorealistic, shallow depth of field, 4k."*
- Describe **motion** — it is a video clip, not a still.
- Keep it **faceless and clean**: no recognizable real people or faces, no
  on-screen text / captions / watermarks / logos (captions are burned in later
  and would clash), no brand marks.
- Match the scene's `mood`, and the same literal subject as `keywords[0]` —
  `broll_prompt` is the rich, cinematic version of that ideal shot.

## Post block

- `title`: ≤ 60 chars, Arabic, states the idea's tension honestly — no
  clickbait lies, no ALL CAPS, no «لن تصدق».
- `description`: 2–3 sentences expanding the idea + 1 line of context.
  No banned phrases, no hashtag walls.
- `hashtags`: 3–5, mix of Arabic topic tags + 1–2 broad reach tags.

## Output contract (frozen — do not improvise fields)

Write `projects/<slug>/script.json`, UTF-8, `ensure_ascii=False` style
(real Arabic characters on disk):

```json
{
  "meta": { "source_url": "...", "audience": "general Arab",
            "dialect": "MSA", "target_seconds": 90 },
  "hook": "...",
  "scenes": [
    { "id": 1, "narration_ar": "...",
      "keywords": [["literal visual set 1"], ["fallback set 2"]],
      "mood": "energetic", "target_seconds": 8 }
  ],
  "post": { "title": "", "description": "", "hashtags": [] }
}
```

`broll_prompt` is the only optional per-scene field — add it (a descriptive
English string, see the B-roll section above) ONLY when generating footage
locally; otherwise omit it. A scene carrying it looks like:

```json
    { "id": 1, "narration_ar": "...",
      "keywords": [["aerial desert highway", "sunset"]],
      "mood": "energetic", "target_seconds": 8,
      "broll_prompt": "A slow cinematic aerial push-in over a lone desert highway at sunset, long shadows, warm haze, gentle drone motion, photorealistic, 4k" }
```

`meta.source_url` provenance: URL-first → the real source URL (from
`source_url.txt`); topic-first → `topic://` followed by the topic
(e.g. `"topic://حقائق عن الصحراء"`), so the origin is always recorded.

Scene ids start at 1, sequential. After writing, ALWAYS validate (ASCII
command — never put Arabic in a shell string):

```
.venv\Scripts\python.exe -c "import json,sys; from pipeline.contract import validate_script; validate_script(json.load(open(sys.argv[1], encoding='utf-8'))); print('script OK')" projects\<slug>\script.json
```

## Self-check before declaring done

1. Originality: no scene maps 1:1 to a transcript paragraph.
2. Hook ≤ 3s, opens scene 1 verbatim, no banned opening.
3. One register throughout; read-aloud test passes.
4. Word count per scene ≈ 2.2–2.6 × target_seconds; total within ±10%.
5. Every keyword set is a literal visual; homonyms disambiguated.
6. Zero banned phrases anywhere (scan narration + post block).
7. Numbers TTS-safe; foreign names have pronunciation.json entries.
8. validate_script passes.
9. Generated-footage projects (`ai_broll`): every scene has a faceless,
   text-free `broll_prompt`; stock-only projects omit it.

Then tell the user the script is ready for **gate 1**: they read it, and
approve with `python run.py approve projects/<slug> --gate 1`.
