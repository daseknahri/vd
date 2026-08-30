# AI video-making — field knowledge base

A durable, curated snapshot of the AI-video landscape as it applies to **this
video factory** (the faceless-Arabic pipeline + the dub path). Built to orient
fast in a field that changes monthly.

> **Snapshot: August 2026.** Prices, model versions, and availability move fast.
> Treat every specific as a *lead to verify* via the linked sources, not gospel.
> To refresh: re-run the `ai-video-field-research` workflow (it re-web-searches
> all 7 domains), then regenerate these files. See **Keeping this fresh** below.

## The one-paragraph takeaway

**The project's spine is already 2026 best practice — do not change it casually.**
The field has consolidated on exactly this chain: an LLM writes the script →
a TTS engine returns **character/word-level timestamps** → those drive
**real-HarfBuzz caption shaping** (never libass for Arabic) → **deterministic
ffmpeg** renders → publishing is one multi-platform API call. This project's
`ElevenLabs with-timestamps → Pillow+libraqm RTL karaoke → code-driven ffmpeg`
is that pattern. The libass RTL-karaoke bug is **still open** in 2026, and the
best English caption SaaS (Submagic, Captions.ai) still render Arabic *reversed
and disconnected* — so **Hard Rule 3 was right**, and there is no SaaS shortcut
that beats the in-house Arabic engine. Keep the spine; adopt selectively at the
edges.

## The docs

| # | Doc | Covers |
|---|-----|--------|
| 01 | [Generation models](01-generation-models.md) | Text/image-to-video: Veo 3.1, Kling 3.0, Seedance 2.5, Runway, Hailuo, Luma; open weights Wan 2.2 / HunyuanVideo / LTX-Video |
| 02 | [Voice: TTS, dubbing & lipsync](02-voice-tts-dubbing-lipsync.md) | ElevenLabs + rivals (Cartesia, Hume, Chatterbox…), **who returns timestamps**, Arabic quality, dubbing & lipsync |
| 03 | [Captions, subtitles & Arabic RTL](03-captions-subtitles-rtl-arabic.md) | Karaoke caption tools, the Arabic RTL shaping problem, why libass fails, forced aligners |
| 04 | [Editing, automation & MCP](04-editing-automation-mcp.md) | Deterministic (Remotion/ffmpeg/Kinocut) vs agentic editing; the plan-vs-render boundary |
| 05 | [Faceless automation & publishing](05-faceless-automation-publishing.md) | End-to-end SaaS vs composable primitives; **unified auto-post APIs** vs native platform limits |
| 06 | [Open-source / self-hosted](06-open-source-selfhosted.md) | The single-GPU self-hosted stack: ComfyUI, open video weights, open TTS, cost tradeoffs |
| 07 | [Recommendations](07-recommendations.md) | The synthesized "winning stack" + concrete upgrades to consider for this project |

## What's validated (keep as-is)

- **ElevenLabs `with-timestamps` → Pillow+libraqm RTL karaoke.** Exactly the
  2026 pattern; the market gap for Arabic RTL is real. (docs 02, 03, 07)
- **Deterministic ffmpeg render; LLM plans, code renders.** The a16z/industry
  consensus boundary — nothing agent-improvised burns pixels. (doc 04)
- **Hard Rule 3 (no libass for Arabic).** `libass` RTL-karaoke bug still open;
  Windows builds still ship libass without HarfBuzz. (docs 03, 04)
- **`process` never auto-posts (Hard Rule 2).** The research agrees the hard
  part of publishing is *policy* (audits, quotas), not code. (doc 05)

## Highest-leverage upgrades to consider (not urgent, weigh against principles)

1. **Generated B-roll instead of stock.** Replace/augment the Pexels→Pixabay
   footage stage with AI-generated, literal-visual scene clips. *Fixed-cost
   path:* self-host **LTX-Video** (fast, 16 GB GPU) or **Wan 2.2** (photoreal
   humans) via ComfyUI's headless API — keeps "only variable cost is TTS".
   *Quality path:* API (Veo 3.1 / Seedance 2.5 / Kling 3.0) via the already-
   connected **Higgsfield MCP** — but per-second billing breaks fixed-cost.
   (docs 01, 06, 07)
2. **Publishing via a unified API** (Blotato / Ayrshare / Postiz), *if/when*
   auto-post is ever enabled — never native TikTok/YouTube/IG APIs (audit gates,
   ~6 uploads/day, 25/day caps). Still behind Hard Rule 2. (doc 05)
3. **Self-hosted TTS to zero the variable cost** — **Chatterbox Multilingual**
   (MIT, Arabic, cloning) + **WhisperX** forced alignment to recover word
   timings (since open TTS won't hand you ElevenLabs-style timestamps). Adds an
   alignment step; ElevenLabs stays the default until this is proven. (docs 02, 06)
4. **Kinocut MCP** (already connected) for *exploration and long→short
   repurposing* on scratch files — never for the pipeline's Arabic render. (doc 04)

## Cautions (things that would quietly break us)

- **Do NOT switch narration to ElevenLabs v3** without first confirming its
  native endpoint returns character alignment — v3 timing on `/with-timestamps`
  is **not confirmed**, and a silent loss of timestamps breaks caption sync.
  Stay on `eleven_multilingual_v2` / `eleven_flash_v2_5`. (docs 02, 07)
- **Do NOT build on OpenAI Sora** — its API **sunsets Sept 24, 2026**. (doc 01)
- **No caption SaaS for Arabic** — Submagic/Captions.ai render it broken. (doc 03)
- **Open video weights lag the closed frontier by ~one generation**, and the
  newest Wan/Kling/Seedance versions are **API-only** (not open). (docs 01, 06)

## Keeping this fresh

This is a snapshot; the field moves monthly. To refresh:

1. Re-run the `ai-video-field-research` workflow (7 parallel web-search
   agents). Note the run's transcript dir, which contains `journal.jsonl`.
2. Regenerate `01`–`07` from that journal (this `README.md` is hand-curated
   and NOT overwritten):
   ```bash
   .venv\Scripts\python.exe scripts\build_research_docs.py <path-to>\journal.jsonl
   ```
3. Skim the diff, update this README's takeaways/cautions, and bump the
   snapshot date.

Cross-refs into the project: caption shaping = **CLAUDE.md Hard Rule 3**;
the dub path = **DUB.md**; the footage stage this could upgrade =
`pipeline/footage.py`.
