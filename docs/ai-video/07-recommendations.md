# Recommendations for the video factory

> **Research snapshot.** Compiled by a web-research sweep for the video-factory project. This is a fast-moving field: prices, versions and availability change monthly. Treat specifics as *leads to verify*, not gospel — follow the sources. Re-run the `ai-video-field-research` workflow to refresh.

## Summary

In 2026 a solo operator's faceless/dub stack has consolidated around a small, proven chain: an LLM writes the script, ElevenLabs does TTS with character-level alignment, captions are shaped with a real HarfBuzz engine (never libass for Arabic), footage is increasingly AI-generated B-roll rather than stock, and publishing is one multi-platform API call. This project already sits on the correct spine: ElevenLabs `with-timestamps` (character alignment) driving Pillow+libraqm RTL karaoke is exactly the pattern the field validates, and libass's RTL-karaoke bug (fills left-to-right) is still open, confirming Hard Rule 3. The highest-leverage 2026 upgrades are: (1) generated B-roll (Veo 3.1 / Seedance 2.0 via the connected Higgsfield MCP) to replace or supplement Pexels/Pixabay stock; (2) an auto-repurposing lane (OpusClip-style long-to-Shorts, or the Kinocut MCP's own repurpose verbs) to multiply output per script; and (3) a guarded multi-platform publish step. The single most important caution is TTS model choice: the expressive Eleven v3 does NOT have confirmed support for the `with-timestamps` endpoint that this pipeline's caption timing depends on, so v3 cannot be dropped in without breaking the karaoke spine. Arabic-first challengers (Hakim, Munsit) now beat ElevenLabs on dialect coverage and regional latency but do not publicly document word-level timestamps, so they are dub/voice candidates only if they expose alignment.

## Tools & models

| Name | Category | Access | Pricing | Notable capability |
|------|----------|--------|---------|--------------------|
| [ElevenLabs Multilingual v2 (with-timestamps)](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps) | voice-tts | api | ~1000 credits/min (1 char=1 credit); overage ~$0.10 per 1000 chars; Creator $22/mo = 121k credits | MSA Arabic TTS with per-character alignment from POST /v1/text-to-speech/{voice_id}/with-timestamps — the endpoint's default and documented model; character start/end times drive karaoke captions. This is the pipeline's current, correct choice. |
| [ElevenLabs Eleven v3 / v3 Conversational](https://elevenlabs.io/docs/overview/models) | voice-tts | api | ~1000 credits/min tier; ~1-2s latency (not low-latency) | Most expressive model, 70+ languages incl. Arabic (ara), audio tags for emotion. BUT timestamp/streaming support on the with-timestamps endpoint is NOT documented — treat as expressiveness upgrade only if alignment is confirmed, else it breaks caption timing. |
| [ElevenLabs Scribe v2](https://elevenlabs.io/speech-to-text/arabic) | speech-to-text | api | transcription from ~$0.22/hour | STT with precise word-level timestamps, 90+ languages incl. Arabic — a stronger alignment fallback than faster-whisper for the align stage / dub transcript. |
| [Hakim (tryhakim.ai)](https://tryhakim.ai/en/alternatives) | voice-tts-arabic | api | free tier 10k chars/mo; paid pricing unpublished | Arabic-first TTS: 15 regional dialects + MSA, sub-120ms regional TTFB (beats ElevenLabs' non-regional routing for Arabic). Word-level timestamps NOT documented — voice/dub candidate only if it exposes alignment. |
| [Munsit](https://munsit.com/blog/elevenlabs-alternatives) | voice-tts-arabic | api | unknown | UAE-based Arabic ASR/TTS with sovereign data; strong dialect accuracy. Timestamps and TTFB not published. |
| [Google Veo 3.1](https://modelslab.com/blog/api/veo-3-1-vs-kling-3-sora-2-ai-video-api-cost-2026) | video-generation | api | ~$0.05/sec (Lite 1080p); ~$0.75 Fast / ~$2.00 Standard for a 5s clip with audio | Generated B-roll / hero shots with NATIVE audio (only tier-1 model that ships audio in-clip); best value on 4-8s clips. Max ~8s per generation. |
| [Seedance 2.0 / 2.5](https://higgsfield.ai/blog/seedance-2-0-pricing-2026) | video-generation | api | 140-425 credits/clip 720p, up to 950 credits for 15s 1080p (Higgsfield plans) | Cheap, longer generated B-roll (up to 15s), joint audio+video, strong multilingual dialogue/lip-sync — reachable through the project's connected Higgsfield MCP. Better for longer single takes than Veo. |
| [Kling 3.0](https://aimlapi.com/blog/best-ai-video-generators-2026-veo-3-1-kling-sora-2-seedance-more-compared) | video-generation | api | ~$0.09-0.14/sec 1080p | Lowest pure cost-per-second for generated B-roll; audio is a separate step. |
| [OpenAI Sora 2 / Sora 2 Pro](https://www.cometapi.com/ai-video-api-pricing/) | video-generation | api | ~$0.08-0.10/sec via 3rd-party APIs; $0.70/sec Pro direct | High-quality generation but AVOID for a durable pipeline: OpenAI's Videos API (sora-2, sora-2-pro) is scheduled for removal Sept 24, 2026. |
| [OpusClip (API)](https://www.opus.pro/blog/youtube-shorts-from-long-video-api) | repurposing | api | paid tiers; API access on higher plans | Long video -> multiple vertical 9:16 Shorts: LLM hook/highlight detection, auto reframe/speaker-track, burned captions. Has an API for pipeline integration — a ready auto-repurposing lane. |
| [AI-Youtube-Shorts-Generator (samuraigpt)](https://github.com/samuraigpt/ai-youtube-shorts-generator) | repurposing | self-hosted | free (open source) | Open-source OpusClip alternative: LLM highlight detection + Whisper + auto vertical crop, no per-clip credits — self-hostable to keep the fixed-cost-first principle. |
| [yt-dlp](https://www.rapidseedbox.com/blog/yt-dlp-complete-guide) | source-download | self-hosted | free (open source) | HD source download for the dub path: `-f bestvideo+bestaudio --merge-output-format mp4` merges separate 1080p/4K streams via ffmpeg. Already the pipeline's ingest tool. |
| [Pillow + libraqm (HarfBuzz)](https://github.com/libass/libass/issues/406) | captions-rendering | self-hosted | free (open source) | Correct Arabic RTL shaping (contextual/isolated/final forms) and right-to-left karaoke fill — the field confirms libass's RTL-karaoke bug is still open, validating this project's Hard Rule 3. Already in use. |
| [Upload-Post / Postproxy / Phyllo](https://www.getphyllo.com/post/using-apis-to-automate-content-upload-on-youtube-instagram-tiktok) | publishing | api | paid SaaS tiers | Single-call multi-platform posting to TikTok, YouTube Shorts, Instagram Reels with per-platform captions — the publish lane the project defers by design. Note IG cap ~100 API posts/24h; TikTok needs approved Content Posting API. |
| [n8n](https://kineclip.com/blog/top-ai-tools-faceless-creators-2026/) | orchestration | self-hosted | free (self-hosted) / paid cloud | Self-hosted glue that chains script -> voice -> B-roll -> captions -> publish; the common 2026 pattern for small operators reaching 70-80% automation with human gates preserved. |

## Key facts (as researched)

- ElevenLabs with-timestamps endpoint: documented default/supported model is eleven_multilingual_v2 (returns character-level + normalized alignment). Eleven v3 compatibility with this endpoint is NOT documented (2026) — swapping to v3 risks breaking the caption-timing spine.
- ElevenLabs model split: only Eleven v3 / v3 Conversational explicitly list Arabic (70+ langs); Multilingual v2 historically supports Arabic (SA/UAE) and is the timestamped path. Flash v2.5 (75ms) has no Arabic.
- ElevenLabs pricing 2026: unified credits, 1 char ~= 1 credit on Multilingual v2 (~1000 credits/min); Creator $22/mo=121k credits, Pro $99/mo=600k; overage ~$0.10/1000 chars (Multilingual), ~$0.05/1000 (Flash).
- libass RTL karaoke is still broken in 2026 (fills left-to-right for Arabic/Hebrew — open libass issue #406). HarfBuzz 14.2.0 (Apr 2026) is the correct shaping engine. This directly validates the pipeline's Pillow+raqm rule.
- Generated B-roll economics: Veo 3.1 ~$0.05-0.15/sec with native audio, max ~8s; Seedance 2.0 cheaper for longer (up to 15s) clips and reachable via the connected Higgsfield MCP; Kling 3.0 lowest per-second but audio separate.
- Sora 2 / Sora 2 Pro Videos API is scheduled for removal on 2026-09-24 — do not build a dependency on it.
- Arabic-first TTS (Hakim: 15 dialects + MSA, sub-120ms regional; Munsit: UAE sovereign) now beat ElevenLabs on dialect/latency, but neither publicly documents word-level timestamps needed for karaoke.
- Auto-repurposing is mature: OpusClip has an API (long->9:16 Shorts, auto-reframe, captions); an open-source equivalent (samuraigpt) runs Whisper + LLM highlight + vertical crop with no per-clip cost.
- Multi-platform publish APIs exist (Upload-Post, Postproxy, Phyllo) but carry limits/approvals: IG ~100 API posts/rolling 24h; TikTok requires approved Content Posting API; per-platform ToS review needed for faceless auto-posting.
- Realistic small-operator automation ceiling in 2026 is ~70-80% (n8n-glued), with humans still spending 20-40 min/video on retention-critical parts — consistent with this project's two-gate design.
- yt-dlp remains the HD-download standard: bestvideo+bestaudio merged via ffmpeg for 1080p/4K; still actively maintained.

## Relevance to the video factory

The project's core spine is already the 2026 best practice and should NOT be changed casually: ElevenLabs character-level alignment (with-timestamps) -> Pillow+libraqm RTL karaoke is exactly what the field validates, and libass's still-open RTL-karaoke bug confirms Hard Rule 3 was correct. Concrete recommendations: (1) STAY on eleven_multilingual_v2 for the with-timestamps path; treat Eleven v3 as a research spike only after confirming it returns alignment on that endpoint — otherwise v3 breaks caption sync (the align.py fallback would then be doing all the work). (2) Add a generated-B-roll provider behind the existing FootageProvider interface (footage.py): wire Veo 3.1 for 4-8s hero scenes and Seedance 2.0 (already reachable via the connected Higgsfield MCP) for cheaper/longer generic scenes, keeping Pexels/Pixabay as the free fallback — this preserves fixed-cost-first while removing 'no acceptable stock match' flags. (3) For the DUB path, keep yt-dlp bestvideo+bestaudio for true HD source, and evaluate Scribe v2 (word-level timestamps, better Arabic) as an upgrade to the faster-whisper align/ingest step. (4) Consider Hakim/Munsit for the dub VOICE only if they expose word timestamps; for now ElevenLabs remains the only alignment-capable option the karaoke renderer can trust. (5) Add an auto-repurposing lane (self-hostable samuraigpt clone, or the Kinocut MCP's video_repurpose/repurpose_plan verbs) to turn one rendered video into multiple Shorts — high ROI, and it can run entirely offline/fixed-cost. (6) Keep publish deferred, but when built, front it with a guarded multi-platform API (Upload-Post/Postproxy) behind the existing gate 2 — respecting IG/TikTok API limits. All of these slot into the module contract (run(project,cfg,env,*,force) + STAGE_DEPENDENTS) without changing the spine.

## Watch list

- Whether Eleven v3 gains official support on the /with-timestamps endpoint (returns character alignment) — if it does, it becomes a drop-in expressiveness upgrade; until then it cannot replace multilingual_v2 in this pipeline.
- Sora 2 / Sora 2 Pro API removal on 2026-09-24 — avoid dependency; watch for the successor API and pricing.
- Arabic-first TTS (Hakim, Munsit) exposing word/character-level timestamps — that would unlock a dialect-accurate, lower-latency alternative to ElevenLabs for both faceless and dub voice.
- Higgsfield/Seedance and Veo pricing and max-clip-length changes — B-roll generation cost is the main new variable cost that would erode the fixed-cost-first principle; re-check per-second rates quarterly.
- TikTok Content Posting API approval requirements and Instagram's 100-posts/24h limit — publishing automation viability for faceless content hinges on evolving platform ToS.
- faster-whisper vs Scribe v2 accuracy on Arabic dialects for the align/ingest step.
- Kinocut MCP repurpose verbs (video_repurpose, video_repurpose_plan) and Higgsfield shorts/clipper tools as in-house, already-connected alternatives to paid OpusClip/Submagic.

## Sources

- <https://elevenlabs.io/docs/overview/models>
- <https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps>
- <https://www.webfuse.com/elevenlabs-cheat-sheet>
- <https://flexprice.io/blog/elevenlabs-pricing-breakdown>
- <https://elevenlabs.io/speech-to-text/arabic>
- <https://tryhakim.ai/en/alternatives>
- <https://munsit.com/blog/elevenlabs-alternatives>
- <https://munsit.com/blog/best-arabic-speech-to-text>
- <https://modelslab.com/blog/api/veo-3-1-vs-kling-3-sora-2-ai-video-api-cost-2026>
- <https://aimlapi.com/blog/best-ai-video-generators-2026-veo-3-1-kling-sora-2-seedance-more-compared>
- <https://www.cometapi.com/ai-video-api-pricing/>
- <https://higgsfield.ai/blog/seedance-2-0-pricing-2026>
- <https://fal.ai/learn/tools/seedance-2-0-vs-veo-3-1>
- <https://www.opus.pro/blog/youtube-shorts-from-long-video-api>
- <https://github.com/samuraigpt/ai-youtube-shorts-generator>
- <https://kineclip.com/blog/top-ai-tools-faceless-creators-2026/>
- <https://oakgen.ai/learn/best-ai-video-tools-faceless-youtube-2026>
- <https://www.getphyllo.com/post/using-apis-to-automate-content-upload-on-youtube-instagram-tiktok>
- <https://www.postpeer.dev/blog/best-tiktok-posting-api>
- <https://postproxy.dev/blog/instagram-reels-api-publishing-guide/>
- <https://www.rapidseedbox.com/blog/yt-dlp-complete-guide>
- <https://github.com/libass/libass/issues/406>
- <https://en.wikipedia.org/wiki/HarfBuzz>
