# Open-source / self-hosted stack

> **Research snapshot.** Compiled by a web-research sweep for the video-factory project. This is a fast-moving field: prices, versions and availability change monthly. Treat specifics as *leads to verify*, not gospel — follow the sources. Re-run the `ai-video-field-research` workflow to refresh.

## Summary

As of Aug 2026, a single 24GB-class workstation (RTX 4090/5090) can run a fully self-hosted AI-video stack, keeping the fixed-cost-first principle intact. For open VIDEO weights the live options are Wan 2.2 (Apache 2.0, the last open-weights Wan — 2.5/2.6/2.7 are API-only), HunyuanVideo 1.5 (Apache 2.0, 8.3B, the accessibility leader at ~14GB VRAM), and LTX-2/2.3/2.5 (Community License, the only open model with NATIVE synchronized audio+video up to 4K/50fps); Mochi 1 and CogVideoX remain lighter/older fallbacks. ComfyUI is the de-facto self-hosted engine and runs headless with a REST/WebSocket API (port 8188), so it slots into a code-driven Python pipeline. For open TTS, Chatterbox Multilingual (MIT, 20+ langs incl. Arabic, ~5s cloning) and XTTS v2 (17 langs incl. Arabic, but non-commercial CPML) are the ElevenLabs-alternative candidates; Kokoro-82M is the fast no-clone narrator; F5-TTS/Piper/Orpheus round out the field. The critical bridge for this project's karaoke captions is WhisperX (faster-whisper + wav2vec2 forced alignment) which recovers sub-100ms word timestamps from ANY generated audio — the open replacement for ElevenLabs' word-level timestamps. Lipsync (LatentSync 1.6, LivePortrait) exists and is strong but is irrelevant to a faceless/keep-source pipeline.

## Tools & models

| Name | Category | Access | Pricing | Notable capability |
|------|----------|--------|---------|--------------------|
| [Wan 2.2 (Wan2.2-T2V/I2V-A14B, TI2V-5B)](https://github.com/Wan-Video/Wan2.2) | open video weights | self-hosted / free (Apache 2.0) | $0 weights; needs a GPU. 14B fp8 ~25GB, GGUF Q5 ~21-25GB, GGUF Q3 ~15GB (fits 24GB w/ quant); 5B fp16 8GB / fp8 6GB. ~8-15min/720p 81f on A6000 | Highest-quality open T2V/I2V with cinematic control; MoE 14B (27B total, 14B active) for quality, dense 5B for 8-12GB cards. NO native audio (S2V is a separate model). |
| [HunyuanVideo 1.5](https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5) | open video weights | self-hosted / free (Apache 2.0) | $0 weights; released 2025-11-21 | Accessibility SOTA: 8.3B DiT, runs on 14GB (GGUF 8-12GB), ~75s/clip on one RTX 4090, native 768x512@24fps 5-10s upscaled to 1080p via 2-stage super-res. HunyuanVideo-Avatar is the audio-driven sibling. |
| [LTX-2 / LTX-2.3 / LTX-2.5](https://en.wikipedia.org/wiki/LTX-2) | open video weights (audio+video) | self-hosted (LTX Community License: free under $10M ARR — NOT Apache) | $0 weights; real-world ~16GB VRAM (Blackwell) for audio-synced 1080p vs the marketed 12GB | First production open model with NATIVE synchronized audio+video, lip sync, up to 20s at 4K/50fps. LTX-2.3 (Mar 2026) is 22B; LTX-2.5 is the current (Aug 2026) line. |
| [Mochi 1 / CogVideoX](https://github.com/THUDM/CogVideo) | open video weights (fallback/light) | self-hosted / free (Apache 2.0) | $0 weights | CogVideoX = accessible entry point, multiple sizes for consumer cards, strong diffusers docs, T2V+I2V. Mochi 1 (Genmo) = older high-motion open model. Both now outclassed by Wan 2.2 / Hunyuan 1.5. |
| [ComfyUI](https://www.runflow.io/blog/comfyui-api-developer-guide) | self-hosted orchestration engine | self-hosted / free (GPL) | $0 | De-facto node engine for all the above weights; runs headless (python main.py --listen), REST+WebSocket API on :8188 (/prompt, /view, /history) drivable from Python — fits a code-driven pipeline. No built-in auth (put behind a reverse proxy). |
| [Chatterbox / Chatterbox Multilingual](https://www.resemble.ai/learn/models/chatterbox-multilingual) | open TTS (voice cloning) | self-hosted / free (MIT) | $0; ~6GB VRAM, gaming GPU | ~5s zero-shot cloning, emotion-exaggeration dial; Multilingual covers 20+ langs INCLUDING ARABIC. Blind-tested preferred over ElevenLabs Turbo ~65%. PerTh watermark auto-embedded. Best ElevenLabs-replacement candidate for this project. |
| [XTTS v2 (Coqui)](https://localaimaster.com/models/coqui-tts) | open TTS (voice cloning) | self-hosted, but CPML license = NON-COMMERCIAL (Coqui defunct, no one to license from) | $0 but non-commercial | ~3-6s cloning across 17 langs incl. Arabic, streaming/real-time. Good quality but the license blocks commercial use — a real blocker for a monetized factory. |
| [Kokoro-82M](https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models/) | open TTS (fixed voices) | self-hosted / free (Apache 2.0) | $0 | Fast lightweight narrator, ~2-3GB VRAM, even CPU. CANNOT clone and ships fixed voicepacks — check Arabic voicepack coverage before relying on it. |
| [F5-TTS / Piper / Orpheus 3B](https://arxiv.org/pdf/2410.06885) | open TTS | self-hosted / free | $0 | F5-TTS = flow-matching research-grade cloning (cross-lingual variants exist); Orpheus 3B = strong cloning; Piper = tiny CPU/Raspberry-Pi narration. F5-TTS has active Arabic community work. |
| [WhisperX](https://github.com/m-bain/whisperX) | forced alignment / word timestamps | self-hosted / free (BSD) | $0; project already ships faster-whisper in ingest | faster-whisper + wav2vec2 forced alignment => sub-100ms WORD-LEVEL timestamps + diarization. The open replacement for ElevenLabs' word timestamps that drive this project's Pillow+raqm RTL karaoke captions. |
| [LatentSync 1.6 / LivePortrait](https://github.com/bytedance/LatentSync) | open lipsync (not needed for faceless) | self-hosted / free | $0 | LatentSync 1.6 = diffusion lipsync at 512x512 (June 2025), high fidelity; LivePortrait = near-real-time portrait animation. Only relevant if the project ever adds AI presenters — irrelevant to faceless/keep-source paths today. |

## Key facts (as researched)

- Wan 2.2 (July 2025, Apache 2.0) is the LAST open-weights Wan. Wan 2.5 (Sep 2025), 2.6 (Dec 2025) and 2.7 are API-ONLY — do not assume newer Wan numbers are downloadable. Wan 3.0 is in beta with open weights unconfirmed.
- HunyuanVideo 1.5 (2025-11-21, Apache 2.0, 8.3B) is the current best fit for a single 24GB workstation: 14GB VRAM, ~75s per clip on one RTX 4090, 1080p via super-res.
- LTX-2 (2026-01-06) is the only open model with native synchronized audio+video (up to 4K/50fps, 20s). License is LTX Community (free under $10M ARR), not Apache. Current line is LTX-2.5 (Aug 2026); LTX-2.3 (Mar 2026) is 22B. Real 1080p audio-synced VRAM ~16GB, not the marketed 12GB.
- Wan 2.2 14B on a 24GB card requires quantization (GGUF Q5 ~21-25GB, Q3 ~15GB, fp8 ~25GB incl. the ~9GB UMT5-XXL text encoder); the dense 5B TI2V fits 8-12GB natively.
- ComfyUI runs fully headless with a REST + WebSocket API on port 8188 (/prompt, /view, /history) — controllable from plain Python, matching this project's code-driven ffmpeg pattern. It has NO built-in auth; bind to localhost / reverse-proxy it.
- Open TTS with Arabic + commercial license: Chatterbox Multilingual (MIT, 20+ langs incl. Arabic, ~5s cloning, ~6GB) is the strongest ElevenLabs alternative. XTTS v2 also does Arabic but is CPML (non-commercial). Kokoro cannot clone.
- WhisperX gives sub-100ms word-level timestamps via wav2vec2 forced alignment (built on faster-whisper) — the open path to recover the word timings that ElevenLabs currently provides, from any generated audio.
- Arabic-specific open TTS is an active 2026 research area: 'Habibi' (unified-dialectal Arabic synthesis) and the Silma TTS Benchmark are emerging references — quality/dialect maturity still needs hands-on validation.
- Fixed-cost math: one RTX 4090/5090-class GPU + electricity turns video-gen and TTS into $0 marginal cost; the only remaining barrier is validating Arabic prosody/dialect vs ElevenLabs and RTL word-alignment accuracy.

## Relevance to the video factory

Two concrete, principle-aligned upgrades. (1) ELIMINATE the only variable cost: swap ElevenLabs TTS for a self-hosted open model. Chatterbox Multilingual (MIT, Arabic, cloning) is the best candidate; XTTS is Arabic-capable but its CPML non-commercial license disqualifies it for a monetized factory. The catch: the current karaoke captions depend on ElevenLabs' per-word timestamps, so an open-TTS path must generate audio then run WhisperX (wav2vec2 forced alignment) to recover word timings — this preserves the existing Pillow+raqm RTL caption stage unchanged and reuses faster-whisper already in ingest. Validate Arabic dialect register + RTL alignment before switching; keep ElevenLabs as the quality baseline. (2) For the ORIGINAL faceless path, open video weights (Wan 2.2, HunyuanVideo 1.5, or LTX-2) run in headless ComfyUI on a single 24GB GPU and could generate B-roll instead of / alongside Pexels-Pixabay stock — still fixed-cost-first (GPU only), and ComfyUI's REST/WebSocket API fits the code-driven, idempotent-stage architecture. HunyuanVideo 1.5 is the pragmatic first target (14GB, ~75s/clip). This is a new FootageProvider-style backend, not a rewrite. The DUB path needs neither video-gen nor lipsync (picture is kept, faces stay); its only relevant win is open TTS + WhisperX for the burned Arabic captions. Lipsync models (LatentSync/LivePortrait) are watch-list only — no use in a faceless/keep-source design.

## Watch list

- Wan 3.0 — beta live as of Aug 2026; open-weights status UNCONFIRMED. If it ships open weights it likely becomes the top self-hosted video model.
- LTX-2.5 exact specs (params/VRAM/audio quality) — Aug 2026 release, details still thin; it's the leading open audio+video model to track for one-pass narrated clips.
- Chatterbox Multilingual Arabic quality/dialect fidelity — needs hands-on A/B vs ElevenLabs on real scripts before trusting it in production; watch the PerTh watermark's effect on downstream re-encoding.
- Habibi / Silma TTS Benchmark and F5-TTS Arabic forks — the Arabic-native open-TTS frontier; re-check quarterly for a model that matches ElevenLabs prosody.
- WhisperX Arabic forced-alignment accuracy on diacritized/undiacritized text — the linchpin for open-TTS karaoke captions; verify word-boundary precision on RTL before committing.
- VRAM/quantization tooling churn (GGUF/fp8 for Wan 14B, Nunchaku/SVDQuant-style int4) — steadily lowers the workstation bar; re-check what fits 24GB.
- HunyuanVideo-Avatar and other audio-driven models — only matters if the project ever pivots away from faceless.

## Sources

- <https://github.com/Wan-Video/Wan2.2>
- <https://www.thundercompute.com/blog/wan-2-2-comfyui-ai-video-model>
- <https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5>
- <https://huggingface.co/tencent/HunyuanVideo-1.5>
- <https://en.wikipedia.org/wiki/LTX-2>
- <https://www.globenewswire.com/news-release/2026/01/06/3213304/0/en/Lightricks-Open-Sources-LTX-2-the-First-Production-Ready-Audio-and-Video-Generation-Model-With-Truly-Open-Weights.html>
- <https://www.orcarouter.ai/blog/wan-3-0-release-date>
- <https://wan27.org/blog/wan-2-6-open-source-guide>
- <https://www.resemble.ai/learn/models/chatterbox-multilingual>
- <https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models/>
- <https://localaimaster.com/models/coqui-tts>
- <https://github.com/m-bain/whisperX>
- <https://whipscribe.com/tools/whisperx>
- <https://github.com/bytedance/LatentSync>
- <https://www.runflow.io/blog/comfyui-api-developer-guide>
- <https://arxiv.org/pdf/2601.13802>
- <https://arxiv.org/pdf/2410.06885>
