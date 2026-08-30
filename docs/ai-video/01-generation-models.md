# Video generation models (text/image-to-video)

> **Research snapshot.** Compiled by a web-research sweep for the video-factory project. This is a fast-moving field: prices, versions and availability change monthly. Treat specifics as *leads to verify*, not gospel — follow the sources. Re-run the `ai-video-field-research` workflow to refresh.

## Summary

As of August 2026 the video-generation field splits cleanly into two camps that matter for a fixed-cost-first pipeline. (1) Closed API models billed per output second: Google Veo 3.1 (the safest premium pick: true 4K + native 48kHz audio/dialogue), OpenAI Sora 2 (best physics, but its API sunsets Sept 24, 2026 — do not build on it), Kuaishou Kling 3.0 (value champion at ~$0.10/sec, best human motion), ByteDance Seedance 2.5 (fast, multi-shot, native audio, cheapest per second), Runway Gen-4.5, MiniMax Hailuo, and Luma Ray 3. (2) Open-weight self-hosted models under Apache 2.0 you can run on one 24GB GPU with zero per-clip cost: Alibaba Wan 2.2 (14B, best photoreal humans), Tencent HunyuanVideo 1.5 (13B, best physics/fluids), and Lightricks LTX-Video 13B / LTX-2 (16GB, fastest, native synced audio) — all ComfyUI-native. Newer flagships (Wan 2.7, Seedance 2.5, Kling 3.0) stay API-only; open weights lag the closed frontier by roughly one generation. All API models are usable programmatically; the connected Higgsfield MCP already exposes ~30 of them (Veo, Kling, Hailuo, Seedance, Flux, Seedream) to Claude Code under one subscription with no API-key juggling. None of these are needed for the core faceless-Arabic captioning path — they are a B-roll/stock-footage replacement, and adopting any API model breaks the "only variable cost is TTS" principle unless you self-host.

## Tools & models

| Name | Category | Access | Pricing | Notable capability |
|------|----------|--------|---------|--------------------|
| [Google Veo 3.1](https://ai.google.dev/gemini-api/docs/video) | text/image-to-video (closed API) | api | Gemini API $0.40/sec with audio (Veo 3.1), Veo 3.1 Fast $0.15/sec; Vertex AI $0.50/sec video-only, $0.75/sec with audio; 4K at premium | Premium quality: true 4K, native audio with synchronized 48kHz dialogue/speech, strong prompt adherence. Safest enterprise pick. Latest official version (Oct 2025); no confirmed Veo 4 as of Aug 2026. |
| [OpenAI Sora 2 / Sora 2 Pro](https://openai.com/index/sora-2/) | text/image-to-video (closed API) | api | Sora 2 $0.10/sec (720p, $0.05 batch); Sora 2 Pro $0.30/sec 720p, $0.50/sec 1024p, $0.70/sec 1080p (~half on batch) | Most physically convincing motion; text+image-to-video with synchronized soundscape/speech/SFX. WARNING: consumer app closed Apr 26 2026; API sunsets Sept 24 2026 — do NOT build on it. |
| [Kling 3.0 (Kuaishou)](https://klingai.com/) | text/image-to-video (closed API) | api | ~$0.10/sec (Kling 3.0); Kling 2.5 Turbo ~$0.31/5s clip via resellers; consumer credits free tier (66/day) to ~$180/mo; 11 API tiers $0.18-$1.70 per 5s | Value champion; best natural human motion (walking, dancing, gestures); Kling 2.6+ adds simultaneous native audio. Tops the Aug 2026 T2V arena leaderboard (score ~1934). I2V + T2V. |
| [ByteDance Seedance 2.5](https://fal.ai/seedance-2.0) | text/image-to-video (closed API) | api | Replicate ~$0.10/5s (480p), ~$0.23/5s (720p); Seedance 1.0 Lite $0.18 per 720p 5s, Pro ~$0.74 per 1080p 5s; ~$3/M video tokens | Unified multimodal (text+image+audio+video in), cinematic multi-shot cuts, native synced audio, realistic physics, up to 50 reference assets, 4-30s at 24fps. Cheapest per-second frontier model. Launched Jul 31 2026. |
| [Runway Gen-4.5 / Gen-4 Turbo](https://docs.dev.runwayml.com/) | text/image-to-video (closed API) | api | Gen-4 Turbo 5 credits/sec = $0.05/sec ($0.25/5s); Gen-4.5 12 credits/sec = $0.12/sec ($0.60/5s); third-party resellers charge more | Strong I2V and cinematic control; well-documented developer API (credits at $0.01 each). Gen-4 Turbo is the cheap fast tier; Gen-4.5 is the flagship. |
| [MiniMax Hailuo (02 / 2.3 / H3)](https://www.minimax.io/) | text/image-to-video (closed API) | api | ~$0.045/sec via fal (~$0.28 per short video); legacy 768p/6s $0.28, 1080p/6s $0.49, 512p/6s $0.10 | Cost-effective I2V/T2V; H3 is the current recommended tier (02 and 2.3 now 'Legacy'). Good motion for the price. Available on fal/Replicate. |
| [Luma Dream Machine (Ray 3)](https://lumalabs.ai/dream-machine) | text/image-to-video (closed API) | api | API from ~$0.08/sec; Ray 3 ~$12.60/60s | Ray 3 model; fast, good motion coherence, keyframe/loop control. API and consumer app. |
| [Higgsfield (MCP aggregator)](https://higgsfield.ai/mcp) | multi-model video/image aggregator + MCP | api | subscription (credit-based); no separate API keys | Connected to this project via MCP. Single subscription exposing 30+ models (Veo, Kling, Hailuo, Seedance, Soul, Cinema Studio, Flux, Seedream) to Claude Code/Cowork with NO per-model API keys. I2V up to 4K, videos up to 15s, consistent characters via Soul. Best programmatic access path for this pipeline. |
| [Alibaba Wan 2.2](https://github.com/Wan-Video/Wan2.2) | text/image-to-video (OPEN WEIGHTS) | self-hosted | $0 per clip (self-host); 14B ~8-12 min per 5s@1080p on A100 | Best open-model photoreal quality for human subjects (skin/hair/faces). 14B (24GB VRAM) + 5B (6-8GB VRAM) variants. ComfyUI-native (T2V, I2V, first-last-frame). Apache 2.0 = commercial use OK. Note: Wan 2.7 (Apr 2026) and 3.0 are API-only, NOT open. |
| [Tencent HunyuanVideo 1.5](https://github.com/Tencent-Hunyuan/HunyuanVideo) | text/image-to-video (OPEN WEIGHTS) | self-hosted | $0 per clip (self-host); ~6-10 min per 5s@1080p on A100 | 13B params; best open-model physics — fluids (water/smoke/fire), cloth, object interactions. 24GB min VRAM. Apache 2.0. ComfyUI compatible. No native audio (separate audio step needed). |
| [Lightricks LTX-Video 13B / LTX-2](https://github.com/Lightricks/LTX-Video) | text/image-to-video (OPEN WEIGHTS) | self-hosted | $0 per clip (self-host); ~3-5 min per 5s@1080p on RTX 4090 | Fastest open model (2-3x others), runs on 16GB VRAM / RTX 4090. LTX-2.5 is the standout for native temporally-aligned audio+video in one forward pass — unique among open models. Apache 2.0, ComfyUI-native. Best fit for a consumer-GPU self-hosted box. |
| [Genmo Mochi 1 / CogVideoX](https://github.com/genmoai/mochi) | text-to-video (OPEN WEIGHTS, older) | self-hosted | $0 per clip (self-host) | Earlier (2024) Apache 2.0 open models, still self-hostable and ComfyUI-supported, but now behind Wan/Hunyuan/LTX on quality. Useful as lightweight/legacy baselines only. |
| [Pika](https://pika.art/) | text/image-to-video (consumer app) | freemium | credit-based subscription | Consumer-focused I2V with effects/templates; weaker programmatic API story than the leaders. Now more of a follower than a frontier model. |

## Key facts (as researched)

- OpenAI Sora 2 API sunsets September 24, 2026 (~3-4 weeks from now); consumer Sora app already closed April 26, 2026. Do not build any dependency on Sora.
- Google Veo 3.1 (Oct 2025) is the latest OFFICIAL Veo; no confirmed Veo 4 as of Aug 2026 (sources conflict; treat Veo 4 as unreleased). Gemini API: Veo 3.1 $0.40/sec w/ audio, Fast $0.15/sec; true 4K + 48kHz dialogue.
- Kling 3.0 is the price/quality value champion at ~$0.10/sec and leads the Aug 2026 blind-vote T2V leaderboard; best natural human motion.
- ByteDance Seedance 2.5 (Jul 31 2026) is the cheapest frontier model per second (~$0.10-0.23 per 5s), with native audio, multi-shot cuts, and up to 50 reference assets.
- Runway Gen-4 Turbo = $0.05/sec, Gen-4.5 flagship = $0.12/sec, billed as credits at $0.01 each on Runway's own API.
- Open-weight leaders are all Apache 2.0 (commercial OK) and ComfyUI-native: Wan 2.2 (14B/24GB, best humans), HunyuanVideo 1.5 (13B/24GB, best physics), LTX-Video 13B (16GB, fastest, native audio in LTX-2.5).
- Newer open-model versions are gated: Wan 2.7 (Apr 2026) and Wan 3.0 are API-only; official Wan open weights stop at 2.2. Open weights trail the closed frontier by ~one generation.
- Wan 2.2 has a 5B variant that runs on 6-8GB VRAM (480p/720p), making self-hosted video generation feasible on a mid-range consumer GPU.
- The connected Higgsfield MCP already gives Claude Code programmatic access to ~30 models (Veo, Kling, Hailuo, Seedance, Flux, Seedream) under one subscription, no per-provider API keys.
- All listed API models are usable programmatically (native REST APIs and/or fal.ai / Replicate / BytePlus aggregators); fal.ai and Replicate are the common multi-model reseller endpoints.

## Relevance to the video factory

These are a potential REPLACEMENT for the Pexels/Pixabay stock-footage stage, not for the core Arabic-caption/TTS spine. Two clear paths. (A) Fixed-cost-first alignment: self-hosting an Apache-2.0 open model (LTX-Video 13B on a 16GB GPU is the best starter given speed; Wan 2.2 14B or its 5B/8GB variant for quality humans; HunyuanVideo for physics-heavy B-roll) keeps the project's 'only variable cost is TTS' principle intact — you'd generate literal-visual scene clips locally instead of searching stock, feeding the same clips/scene_XXX.mp4 slots the footage stage already produces. This fits the existing FootageProvider interface as a new provider behind the same contract. (B) Convenience path: the already-connected Higgsfield MCP lets Claude Code call Veo/Kling/Seedance directly with no key management — fastest to prototype, but every clip is a per-second variable cost that violates the fixed-cost design, so gate it behind an explicit opt-in. IMPORTANT for both: generated clips are silent B-roll — you must still MUTE/ignore any model-generated audio, because Hard Rule 1 (nothing from the source enters output) and the pipeline's design keep ElevenLabs TTS as the sole voice and Pillow+raqm as the sole caption path; do NOT let Veo/Seedance native-audio or burned-in text leak into the render. For the DUB path these generation models are largely irrelevant (dub keeps the source picture). Do NOT adopt Sora (API dead Sept 24 2026). If you add generation, wrap it as an idempotent footage provider that writes to the existing scene-clip filenames and never bypasses the two human gates.

## Watch list

- Sora 2 API sunset on Sept 24 2026 — confirm the exact cutoff and whether OpenAI ships a successor/replacement endpoint.
- Veo 4 — rumored but unconfirmed as of Aug 2026; watch Google I/O follow-ups and 'Gemini Omni' unified creation platform.
- Wan open weights — whether Wan 2.7 / 3.0 ever get an open-weight drop or stay API-only (currently official open weights stop at Wan 2.2).
- LTX-2.5 native-audio open weights — the only open model with synced audio; track its VRAM and license terms.
- Kling 3.0 official API per-second pricing and rate limits (vs reseller estimates).
- Seedance 2.5 official (BytePlus/Volcano) pricing and whether it lands as an open release.
- Higgsfield MCP model roster + credit pricing changes — the actual programmatic access surface for this project.
- Emerging entrants seen in Aug 2026 leaderboards: Grok Imagine Video 1.5, 'Happy Horse 1.0' — verify these are real and their access model.

## Sources

- <https://www.eesel.ai/blog/sora-2-pricing>
- <https://costgoat.com/pricing/sora>
- <https://www.getaiperks.com/en/blogs/44-best-ai-video-generators-2026>
- <https://ai.google.dev/gemini-api/docs/video>
- <https://www.veo3ai.io/blog/veo-3-api-pricing-2026>
- <https://www.aifreeapi.com/en/posts/veo-3-1-pricing>
- <https://renderful.ai/blog/kling-api-pricing>
- <https://piapi.ai/kling-2-6>
- <https://apiframe.ai/guides/runway-api-guide>
- <https://apostle.io/pricing/runway-gen-4/>
- <https://cellcog.ai/blog/seedance-2-5-pricing/>
- <https://fal.ai/seedance-2.0>
- <https://felloai.com/minimax-pricing/>
- <https://www.ai-pirates.com/en/glossar/luma-dream-machine>
- <https://higgsfield.ai/mcp>
- <https://higgsfield.ai/blog/5-Best-AI-Video-Models-2026-Tested-Compared>
- <https://www.aimagicx.com/blog/open-source-ai-video-models-comparison-2026>
- <https://ltx.io/blog/open-source-video-generation-models-guide>
- <https://wan27.org/blog/wan-2-7-open-source-guide>
- <https://www.thundercompute.com/blog/wan-2-2-comfyui-ai-video-model>
- <https://localaimaster.com/blog/wan-video-generation-guide>
- <https://llm-stats.com/leaderboards/best-ai-for-video-generation>
- <https://www.teamday.ai/blog/best-ai-video-models-2026>
