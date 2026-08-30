# Editing, automation & MCP servers

> **Research snapshot.** Compiled by a web-research sweep for the video-factory project. This is a fast-moving field: prices, versions and availability change monthly. Treat specifics as *leads to verify*, not gospel — follow the sources. Re-run the `ai-video-field-research` workflow to refresh.

## Summary

As of Aug 2026 the field splits cleanly into two layers that the video-factory design already respects. (1) Deterministic code-first rendering: ffmpeg-wrapping frameworks (Remotion/React, Motion Canvas + its automation fork Revideo) and guardrailed MCP servers (Kinocut, the project's connected editor) turn a spec into pixels reproducibly. (2) LLM/agentic "decide-what-to-do" layers (Video Use, LAVE, OpusClip/Vizard/Klap auto-clippers) that plan cuts, pick moments, and assemble timelines but still hand rendering to ffmpeg. The 2026 consensus (a16z, cutback, solosoft) is exactly the project's architecture: LLMs draft the plan/script, deterministic ffmpeg renders, and nothing agent-improvised burns final frames. The single most load-bearing external fact for this project: the ffmpeg + libass "simple shaping" bug on Arabic is STILL unresolved (libass issue #682 open; HarfBuzz 14.2.0 shipped Apr 2026 but Windows ffmpeg builds still don't link it into libass), so Hard Rule 3 (never burn Arabic through libass) remains correct and necessary. Kinocut is directly usable for the deterministic assembly/trim/repurpose/QC spine, but its caption path is Whisper+SRT/libass burn with no documented RTL handling, so Arabic captions must stay on the project's own Pillow+raqm renderer.

## Tools & models

| Name | Category | Access | Pricing | Notable capability |
|------|----------|--------|---------|--------------------|
| [Kinocut](https://github.com/KyaniteLabs/kinocut) | video-editing MCP server (connected to this project) | self-hosted / free / open-source (Apache-2.0); optional paid gen backends off by default | Free (Apache-2.0, no keys/metering for core); latest v1.15.0 published 2026-08-19 | Local guardrailed ffmpeg wrapper for AI agents: 196 typed MCP tools / 167 CLI commands (v1.15.0). Preflight validation, 'Video Receipt' provenance (deterministic spec/input/output hashes), quality gates and a publish checkpoint before render. Core ops: trim/merge/resize/crop/overlay/export, scene detect, thumbnails/storyboards, audio normalize/stem-separate/silence-removal, Whisper transcription, SRT burn, shorts/reels/tiktok repurpose packages, layered compositing. First-class Windows support (portable projectstore file locking, UTF-8 stdio) landed in 1.15.0. Deterministic-first design matches the project's fixed-cost philosophy; suited to the assembly/trim/repurpose/QC spine. Caveat: caption burn is Whisper+SRT via libass with NO documented RTL/Arabic handling — do NOT route Arabic captions through it; keep Pillow+raqm. |
| [Remotion](https://www.remotion.dev) | code-first programmatic video framework (React) | api / self-hosted (npm); source-available with paid company license | Free for teams <=3 (commercial OK); Company $100/mo (4+), Enterprise from $500/mo | Write video as React components, render to MP4/WebM server-side, scale via Lambda. @remotion/captions (word-level timestamps, silence-based page breaks) + @remotion/install-whisper-cpp for local caption generation; captions are a first-class timeline item in the Editor Starter. 'Remotion Skills' (agent layer for Claude Code, released Jan 2026) generates/modifies/renders via natural language. Relevance: a viable ALTERNATIVE renderer for RTL karaoke captions/overlays because it shapes Arabic correctly through Chromium/HarfBuzz (unlike ffmpeg-libass) — but pulls in a Node+headless-Chromium dependency, heavier than the current Pillow+raqm+ffmpeg path. |
| [Revideo](https://re.video) | code-first animation framework (automation-focused) | self-hosted / free / open-source | Free (open-source) | Open-source fork of Motion Canvas aimed at automated video pipelines: keeps the generator/timeline animation model and adds a headless rendering API, template system, audio support, library-first API, and a React player for browser preview. Good fit for scripted, parametrized explainer/animated-caption segments rendered in a pipeline. Browser-lineage text stack shapes Arabic correctly. |
| [Motion Canvas](https://motioncanvas.io) | code-first animation framework | self-hosted / free / open-source (MIT) | Free (open-source) | TypeScript generator-function animation with tweening, scene graph, and a real-time visual editor; built for hand-crafted explanatory/educational animation rather than headless batch production (that's what Revideo adds). Alternative mental model to Remotion: scripted sequential timelines vs React components. |
| [Video Use](https://www.solosoft.dev/post/video-use-ai-editing-2026/) | agentic / LLM-driven video editing (open-source) | self-hosted / free / open-source | Free (open-source) | Lets coding agents edit video through natural-language commands — filler-word removal, color grading, subtitles, animations, audio fades — described as token-efficient and using ffmpeg for the actual render with deterministic, keyless fallbacks. Concrete example of the recommended pattern: LLM plans the edit, ffmpeg executes it. Useful reference for exposing editing intent to an agent without letting the model improvise final pixels. |
| [OpusClip](https://www.opus.pro) | auto-repurposing long-to-shorts | freemium; API gated to Business/enterprise plan | Free tier 60 credits/mo; Starter $15/mo (150 credits); API = enterprise only | AI picks viral moments from a long video and produces vertical shorts with auto-captions and reframing. API only on the enterprise/Business tier (custom pricing), so not cheaply scriptable. Variable per-clip cost conflicts with the project's fixed-cost-first principle; Kinocut's local repurpose/shorts tools cover the same need for free. |
| [Vizard](https://vizard.ai) | auto-repurposing long-to-shorts | freemium; public API on paid plans | Creator ~$29/mo; API included on paid plans (separate rate pool) | Long-video-to-clips with auto-captions/reframing; offers a public API on paid plans with a separate rate pool independent of the credit balance — the most straightforwardly scriptable of the mainstream clippers. Still a recurring per-use cost, so off-thesis for the fixed-cost pipeline; relevant mainly if the dub/repurpose path ever wants a hosted clipper. |
| [Klap](https://klap.app) | auto-repurposing long-to-shorts | paid; public API billed per operation | ~$29/mo + API $0.32-0.48 per operation | Shorts generation with a public API billed per operation (~$0.32-0.48/op) on top of the subscription — transparent metered pricing if a hosted clipper is ever needed. Same fixed-cost caveat as OpusClip/Vizard. |
| [ffmpeg + libass / HarfBuzz](https://github.com/libass/libass/issues/682) | rendering engine (RTL caveat) | self-hosted / free / open-source | Free (open-source) | ffmpeg remains the universal deterministic render backend under Kinocut, Remotion, Revideo and Video Use. CRITICAL for this project: the '-vf subtitles'/libass path still uses simple (legacy) Arabic shaping unless libass is linked against HarfBuzz, and libass issue #682 remains OPEN in 2026; Windows ffmpeg builds ship libass without HarfBuzz, producing tofu/wrong joined forms. HarfBuzz itself is healthy (stable 14.2.0, Apr 20 2026) but that does not fix the Windows-ffmpeg-libass gap. drawtext also does not do RTL/complex shaping. Conclusion: Hard Rule 3 stands — burn Arabic via Pillow+raqm (real HarfBuzz), export .ass only as a portable artifact. |

## Key facts (as researched)

- Kinocut latest = v1.15.0 (published 2026-08-19); 196 MCP tools + 167 CLI commands; Apache-2.0; free/local; first-class Windows support (portable file locking, UTF-8 stdio) added in 1.15.0.
- Kinocut's caption path is Whisper transcription + SRT + burned captions with NO documented RTL/Arabic handling — treat as unsafe for Arabic; keep the project's Pillow+raqm renderer.
- libass Arabic 'simple shaping' bug (issue #682) is STILL open in 2026; Windows ffmpeg builds do not link HarfBuzz into libass — directly validates the project's Hard Rule 3.
- HarfBuzz stable release 14.2.0 shipped 2026-04-20 (shaping engine is current; the gap is ffmpeg/libass build linkage, not HarfBuzz).
- Remotion pricing: free for <=3-person teams incl. commercial; Company $100/mo (4+); Enterprise from $500/mo. 'Remotion Skills' agent layer released Jan 2026. Ships @remotion/captions + local Whisper.cpp.
- Revideo = automation-focused open-source fork of Motion Canvas: headless rendering API, templates, audio, React preview player — the code-first option built for batch pipelines.
- Auto-clipper API access in 2026: OpusClip API = enterprise/Business only; Vizard = public API on paid plans (separate rate pool); Klap = public API metered ~$0.32-0.48/operation. All recurring variable cost (off-thesis for fixed-cost pipeline).
- 2026 agentic-editing consensus (a16z 'It's time for agentic video editing', cutback, solosoft): LLMs plan/decide, ffmpeg renders deterministically — LLM systems complement, not replace, ffmpeg. Mirrors the project's LLM-writes-script / deterministic-ffmpeg-renders / no-LLM-caption-burn split.
- Open-source agentic editors to note: Video Use (coding-agent NL editing, ffmpeg render, keyless deterministic fallbacks) and Vanta (itsjwill/vanta, open-source AI video engine built on Remotion with animated captions/voice).

## Relevance to the video factory

Faceless-Arabic pipeline: the research CONFIRMS the two most load-bearing design choices. (1) Hard Rule 3 (never burn Arabic through libass) is still required in Aug 2026 — libass#682 remains open and Windows ffmpeg builds ship libass without HarfBuzz; Pillow+raqm stays the correct caption renderer. (2) The deterministic-render / LLM-plan boundary is the industry-endorsed pattern (a16z/cutback/solosoft), so the architecture is sound, not behind. Concrete adoption path: the connected Kinocut MCP (v1.15.0, free, Apache-2.0, now Windows-first-class, deterministic receipts + preflight + quality gates) is a good fit for the deterministic spine — trim/merge/overlay/scene-detect/QC/repurpose and shorts packaging — WITHOUT touching Arabic caption burning, which must remain on the in-house Pillow+raqm path (Kinocut has no documented RTL support). If a richer motion-caption/template look is ever wanted, Remotion or Revideo can render Arabic correctly (they shape via Chromium/HarfBuzz), at the cost of a Node/headless-Chromium dependency — evaluate against the fixed-cost/simplicity principle before adopting. Dub path: same split — Kinocut can mute/overlay/duck/assemble deterministically; hosted long-to-shorts clippers (OpusClip/Vizard/Klap) are recurring variable cost and off-thesis, so prefer Kinocut's local repurpose tools if shorts are ever needed. Do NOT let any agentic editor (Video Use-style) improvise the final Arabic caption burn; keep the human gates and deterministic render.

## Watch list

- libass issue #682 / Windows ffmpeg (gyan, BtbN) builds — watch for the day a mainstream Windows build ships libass linked against HarfBuzz; that would be the only event that could relax Hard Rule 3.
- Kinocut releases past 1.15.0 — whether it adds documented RTL/Arabic caption shaping (would make its caption tools usable here) and how its Windows projectstore locking behaves in practice.
- Remotion Skills + @remotion/captions RTL handling — confirm Arabic word-level karaoke renders correctly and whether the Node/Chromium footprint is worth it vs Pillow+raqm.
- Revideo headless-render maturity for batch Arabic caption/explainer segments.
- Open-source agentic editors (Video Use, Vanta) — whether they add safe, deterministic caption-burn boundaries usable as a reference for the pipeline's own agent layer.
- Auto-clipper API pricing/terms drift (OpusClip enterprise-only API, Vizard rate pools, Klap per-op $0.32-0.48) if the dub/repurpose path ever considers a hosted clipper.
- ElevenLabs MCP connectivity — flagged this session as CONNECT_TIMEOUT; not editing-domain but it gates the TTS+timestamp step that feeds caption timing.

## Sources

- <https://github.com/KyaniteLabs/kinocut>
- <https://kinocut.dev/>
- <https://pypi.org/project/kinocut/1.10.0/>
- <https://www.remotion.dev/docs/captions/caption>
- <https://gaga.art/blog/remotion-skills/>
- <https://www.toolworthy.ai/tool/remotion>
- <https://www.pkgpulse.com/guides/remotion-vs-motion-canvas-vs-revideo-programmatic-video-2026>
- <https://rendercomp.com/blog/best-programmatic-video-tools-2026/>
- <https://midrender.com/revideo>
- <https://github.com/libass/libass/issues/682>
- <https://en.wikipedia.org/wiki/HarfBuzz>
- <https://a16z.com/its-time-for-agentic-video-editing/>
- <https://cutback.video/blog/what-is-agentic-video-editing>
- <https://www.solosoft.dev/post/video-use-ai-editing-2026/>
- <https://reap.video/reports/state-of-top-ai-video-clipping-tools-2026>
- <https://klap.app/blog/opus-clip-pricing>
- <https://www.ssemble.com/blog/vizard-vs-opus-clip-vs-ssemble>
- <https://checkthat.ai/brands/opusclip/pricing>
- <https://github.com/itsjwill/vanta>
