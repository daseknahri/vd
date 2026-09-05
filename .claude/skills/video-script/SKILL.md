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

## What makes it GREAT — retention playbook

Structure alone produces a *correct* video; these techniques make one people
watch to the end and save. The goal is not "a working script" — it is genuinely
great content. Apply all of these, not just the arc above.

- **Beat sheet (scale to `target_seconds`):** hook (~6%) → context, who/why-care
  (~8%) → escalation: 2–4 compounding **"but"** beats, each landing *worse* than
  the last (~30%) → the **pivot**, the surprising turn/observation, which MUST
  land at or before the midpoint (~9%) → **proof**: 1–2 concrete micro-payoffs
  that show the idea in miniature *before* you name it (~17%) → **payoff**: the
  idea stated plainly (~13%) → closing thought: a resonant callback, no CTA
  (~8%). Scene count stays the existing 6–12; these are proportions, not new
  fields.
- **"But / therefore," never "and then":** before writing scene N+1, say the
  join out loud. If the only word that fits between scene N and N+1 is "then"
  (ثم), the beats are a timeline, not a story — rewrite N+1 as a complication
  (لكن) or a consequence (لذلك) of N. If a reader could reorder your scenes
  without breaking anything, there is no causal chain.
- **Open a curiosity gap in the hook, close it at the end.** State the viewer's
  own unresolved stakes (a question, a withheld cause, a cold-open into the
  darkest concrete moment) — never bio/setup first. The tension you open is a
  debt; the payoff pays it. Do not open a loop the content cannot pay off.
- **Re-hook every 10–15s.** Every scene cut is already a pattern interrupt (new
  image, new pan) — but also plant 2–3 *small* open loops beyond the main hook
  (an unanswered "why", a foreshadowed detail) so a viewer drifting at second 40
  gets a fresh reason to stay. Never run a single unbroken exposition stretch
  longer than ~40s of runtime; break it with a re-hook.
- **Escalate, don't list.** If two scenes in the escalation block could swap
  order without weakening the video, they aren't escalating — make each loss or
  stake land heavier than the one before.
- **Proof before payoff.** Land 1–2 small, concrete relief beats before the big
  abstract idea — an unbroken build with zero relief loses viewers before they
  reach the point.
- **The payoff is a reframe, not a fact.** Name a principle the viewer can apply
  to their *own* life, not trivia about the subject. Aim it at awe or moral
  elevation (the emotions most correlated with sharing), and land it as one
  short, quotable line — assume someone screenshots only your last sentence.
- **Close with a callback, never a CTA.** Answer, echo, or re-pose the hook's
  exact question (bookend). A closed loop invites a mental — or literal —
  rewatch; a bolted-on «شاركونا رأيكم» never does. Stop the instant the
  resonant line lands; no coda after it.
- **Sentence-length variance = caption cadence.** Alternate short declaratives
  with longer elaborative sentences; short lines double as natural caption/edit
  points. Three-plus long sentences in a row flattens the karaoke rhythm.
- **Arabic-specific:** classical parallelism (balanced, similar-length clauses,
  الموازنة) is worth using *structurally* at the hook and closing line
  specifically, where quotability matters most — never as fancy vocabulary
  across the body (literary stiffness stays banned). Arabic reads heavier per
  word than English, so bias to the short end of the 2.2–2.6 words/sec range at
  the hook and re-hook beats.

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

## Writing for the voice-over (delivery)

The script is read by a TTS voice whose delivery is driven by what you write —
a flat script gets a flat read. Write so the voice can *mean it*:

- **`mood` now directs the VOICE, not just the footage.** The voice stage maps
  each scene's `mood` to emotion + pacing — `energetic` = brighter and faster,
  `archival` = slow, low and heavy, `calm` = warm and unhurried — and to the
  breath (a designed pause) after the scene. Assign `mood` to the scene's
  **emotional beat**, deliberately; it is a performance direction now.
- **Punctuation is pacing** — the only in-scene timing you control:
  - `…` before a reveal, or ending a line you want to hang, makes the voice
    slow and let the moment land.
  - Commas add breath; a comma-light line reads fast and urgent.
  - Short sentences push energy; long ones calm and slow. **Vary them** — a
    short sentence after two long ones hits like a punch.
- **Emphasis without CAPS.** Arabic has no letter case, so stress a key word by
  putting it **last, right before a pause or period**, and/or end the line with
  `!` (intensity) or `?` (a lift). One emphasis per sentence — if everything is
  stressed, nothing is.
- **Selective tashkeel for prosody.** A mis-vocalized word is a top cause of a
  flat, robotic read. For a genuinely ambiguous word, a proper name, or the one
  word you most want stressed, add a *fully-diacritized spoken respelling* to
  `pronunciation.json` (display text stays bare — same mechanism as foreign
  names). Never diacritize whole sentences; that over-constrains the voice.

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

**Attention upgrades** — a technically correct clip can still fail to stop the
scroll. The prompt's job is grabbing and holding *human* attention, not looking
"pretty":

- **Match the engine actually rendering it.** Two engines exist (`footage.broll.engine`):
  - `video` (LTX) — photoreal moving clips: reward the cinematography language
    above (camera motion, lighting, "photorealistic, 4k").
  - `image` (SDXL storybook, `pipeline/broll_image.py`) — one illustrated still
    per scene, panned by Ken Burns. It has a FIXED style baked in (flat
    cel-shaded, bold ink outlines, pastel, vector-clean) and a negative prompt
    that suppresses "watercolor", "painterly", "dark/moody/dramatic shadows",
    and "cluttered/busy" detail. For `image` projects those words are dead
    weight — never spend the prompt on texture, film-camera, or darkness; spend
    it on the bullets below. (The engine also strips any `"STYLE — CONTENT"`
    lead-in, so lead with the content.)
- **One dominant subject, one explicit action or expression.** Never "a scene
  showing X and Y and Z" — two competing focal points read as clutter at feed
  speed. Isolate the subject against a simplified field for contrast pull.
- **Push the emotion past neutral.** State the exact expression/posture for the
  beat ("eyes wide with wonder", "shoulders slumped, head down", "a small
  hopeful smile") — the default character look reads as generically friendly,
  which under-sells a tension or despair beat. Small-screen + scroll speed needs
  caricature-level clarity, not subtlety.
- **Carry mood with palette + symbolism, not darkness.** One colour-temperature
  choice per scene (warm gold = hope/payoff; muted cool gray-blue = loss/
  tension), plus symbolic distance for heavy material (silhouettes, "no visible
  faces, symbolic and tasteful"). This is how the `image` engine conveys a dark
  beat when it cannot use dark lighting.
- **Leave an explicit empty landing zone in the upper two-thirds** ("plain sky
  above", "bare wall behind"). Captions burn into roughly the lower quarter, and
  the `image` still is panned ~18% oversized in a random diagonal direction, so
  the subject needs safe margin on all four sides — not rule-of-thirds room
  aimed one way.
- **One-glance test:** if parsing the frame would take a viewer more than a
  second, cut detail rather than add description.

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
2. Hook ≤ 3s, opens scene 1 verbatim, no banned opening, and opens a curiosity
   gap (stakes/question/withheld cause) — not bio or setup.
3. One register throughout; read-aloud test passes.
4. Word count per scene ≈ 2.2–2.6 × target_seconds; total within ±10%.
5. Every keyword set is a literal visual; homonyms disambiguated.
6. Zero banned phrases anywhere (scan narration + post block).
7. Numbers TTS-safe; foreign names have pronunciation.json entries.
8. validate_script passes.
9. Generated-footage projects (`ai_broll`): every scene has a faceless,
   text-free `broll_prompt`; stock-only projects omit it.
10. **Retention:** scene joins are "but/therefore", not "and then" (scenes
    can't be freely reordered); the pivot lands by the midpoint; 1–2 proof
    beats precede the payoff; the payoff is a quotable reframe; the close
    callbacks the hook. No unbroken exposition stretch over ~40s.
11. **Attention (image engine):** each `broll_prompt` has one dominant subject
    with an explicit expression/posture, mood carried by palette/symbolism (not
    "dark/dramatic"/texture words), and an empty landing zone in the upper
    two-thirds.
12. **Voice-over:** every scene's `mood` matches its emotional beat (it now
    drives vocal delivery); key lines use `…` / short sentences for pacing and
    put the stressed word last; any ambiguous or must-stress word has a
    tashkeel'd respelling in `pronunciation.json`.

Then tell the user the script is ready for **gate 1**: they read it, and
approve with `python run.py approve projects/<slug> --gate 1`.
