# Voice: TTS, dubbing & lipsync

> **Research snapshot.** Compiled by a web-research sweep for the video-factory project. This is a fast-moving field: prices, versions and availability change monthly. Treat specifics as *leads to verify*, not gospel — follow the sources. Re-run the `ai-video-field-research` workflow to refresh.

## Summary

As of Aug 2026, ElevenLabs remains the default for high-quality multilingual TTS with word/character timestamps, but it is no longer the only game in town for the two things this project depends on: character-level timing and Arabic. Its `/v1/text-to-speech/{voice_id}/with-timestamps` endpoint (streaming + non-streaming) returns per-character `character_start_times_seconds`/`character_end_times_seconds` and is confirmed on `eleven_multilingual_v2` (default) and `eleven_flash_v2_5`; timestamp support on the new flagship `eleven_v3` (expressive, 70+ langs) via the native endpoint is NOT clearly confirmed by ElevenLabs docs (third-party wrappers advertise "V3 timing," which is not the same thing) — so switching narration to v3 for the karaoke path is a real risk. Cartesia Sonic-3 (44 langs, sub-100ms, word timestamps) and Hume Octave 2 (word- AND phoneme-level timestamps) are now credible timestamp-returning challengers, and the cloud incumbents Azure TTS (~$1/M chars), Amazon Polly (SpeechMarks) and Google Cloud TTS all return word timing far cheaper than ElevenLabs. For genuine Arabic dialect authenticity, Arabic-native Munsit/Faseeh (25+ dialects, on-prem/VPC) outclasses ElevenLabs' "Arabic-as-one-of-90-languages" MSA generalization. Automated dubbing is dominated by HeyGen (lipsync included, 175+ langs), ElevenLabs Dubbing v2 (audio-only, 90+ langs) and Rask; open-source lipsync (LatentSync, Wav2Lip) is language-agnostic and self-hostable. Open-source TTS (Kokoro, Chatterbox) is strong for English but weak for Arabic.

## Tools & models

| Name | Category | Access | Pricing | Notable capability |
|------|----------|--------|---------|--------------------|
| [ElevenLabs (eleven_multilingual_v2 / eleven_flash_v2_5 / eleven_v3)](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps) | tts-api | api | Creator $22/mo = 100k credits (~100 min); Pro $99/mo = 500k credits (~500 min); 1 credit ≈ 1 char; Creator overage $0.30 / 1k chars | Best-in-class multilingual TTS + voice cloning. multilingual_v2 (29 langs, 10k char) and flash_v2_5 (32 langs, ~75ms, 40k char) both work with the /with-timestamps endpoint returning per-character start/end seconds — the exact primitive this project's karaoke captions depend on. eleven_v3 (70+ langs, expressive, 5k char cap) is the flagship but native timestamp support is unconfirmed. Supports previous_text/next_text for prosody continuity. |
| [ElevenLabs Dubbing v2](https://elevenlabs.io/docs/overview/capabilities/dubbing) | dubbing-api | api | ~2000 credits/min (Creator 100k credits ≈ 50 min/mo) | End-to-end video/audio dub in 90+ languages incl Arabic; auto transcribe→translate→revoice. Audio-only (no lipsync/video). 'Bring your own transcript' (segments array with start/end + speaker) is enterprise-only. Relevant to the project's dub path but a black box vs the current mute+overlay+burned-captions approach. |
| [ElevenLabs Scribe v2 (STT)](https://elevenlabs.io/docs/overview/models) | stt-alignment | api | usage-based (STT credits) | Speech-to-text, 90+ langs incl Arabic, 'precise word-level timestamps'; realtime variant ~150ms. Useful as an alignment source (could power/replace the align.py fallback, or timestamp the dub-path subtitles from an existing voiceover). |
| [Cartesia Sonic-3 (Sonic 3.6)](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest) | tts-api | api | usage-based; positioned cheaper than ElevenLabs per minute (verify) | Ultra-low-latency (sub-100ms TTFB, WebSocket) TTS, 44 languages incl Arabic, returns word-level timestamps + audio-context management. Credible timestamp-returning alternative to ElevenLabs, especially for realtime; Arabic quality vs ElevenLabs unverified. |
| [Hume Octave 2](https://dev.hume.ai/docs/text-to-speech-tts/timestamps) | tts-api | api | usage-based (verify) | Expressive/emotion-steerable TTS that returns BOTH word- and phoneme-level timestamps in the TTS response — the phoneme granularity is unusual and useful for tight caption/lipsync timing. Multilingual; Arabic quality unverified. |
| [OpenAI gpt-4o-mini-tts](https://developers.openai.com/api/docs/guides/text-to-speech) | tts-api | api | ~$0.015 / 1k chars | Cheap, simple, steerable-by-instruction TTS. BUT no native word/character timestamps and voices are English-optimized (Arabic pronunciation/naturalness weak) — poor fit for this project's Arabic karaoke path. |
| [Munsit / Faseeh (Arabic-native)](https://munsit.com/blog/best-arabic-tts) | tts-api-arabic | api / self-hosted | from $8/mo (200k credits); free tier; VPC/on-prem enterprise | Purpose-built Arabic TTS trained on 30k+ hrs real dialectal audio; 25+ dialects (Emirati/Khaleeji/Najdi/Hijazi, Levantine, Egyptian, Maghrebi, MSA) + Arabic-English code-switching; WebSocket streaming <150ms; voice cloning; on-prem/VPC/on-device. Best dialect authenticity for Arabic vs ElevenLabs' MSA generalization. Timestamp granularity for captions not clearly documented — verify before relying on it. |
| [Amazon Polly](https://munsit.com/blog/best-arabic-tts) | tts-api-cheap | api / paid | ~$4 / 1M chars (neural) | Neural Arabic voices: MSA (Zeina) + Gulf ar-AE (Hala, Zayd). Returns SpeechMarks (word/sentence/viseme/SSML) with time offsets — directly usable for karaoke word timing at a fraction of ElevenLabs cost. Fits the project's fixed-cost-first ethos as a fallback voice. |
| [Microsoft Azure TTS](https://munsit.com/blog/best-arabic-tts) | tts-api-cheap | api / self-hosted (containers) | ~$1 / 1M chars (neural) | Multiple Arabic locales (ar-AE/ar-SA/ar-EG/ar-LB/ar-OM), SSML control, WordBoundary events (word-level timing) — usable for karaoke captions. Cheapest of the timestamp-capable clouds; containerizable/on-prem via Azure Stack. |
| [Google Cloud TTS](https://munsit.com/blog/best-arabic-tts) | tts-api-cheap | api | ~$4 / 1M chars (WaveNet) | Arabic MSA only (ar-XA), returns timepoints (SSML <mark>-based timing, not fully automatic word timing). Weaker Arabic dialect coverage than Azure/Polly; usable but MSA-limited. |
| [Kokoro-82M](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026) | tts-open-source | self-hosted / free | free (self-host GPU/CPU) | Tiny (82M params, Apache-2.0), runs in 2-3GB VRAM or CPU, OpenAI-compatible wrappers (fastkokoro). Fast English/narration; Arabic support weak/absent. Token-level timing available via its pipeline. Good for zero-variable-cost English but not the Arabic path. |
| [Chatterbox / Chatterbox Turbo (Resemble AI)](https://findskill.ai/blog/best-open-source-tts-2026/) | tts-open-source | self-hosted / free | free (self-host) | MIT-licensed 0.5B, best open-source naturalness + voice cloning (65.3% listener preference vs ElevenLabs 24.5% in cited test). Primarily English; Arabic maturity limited. Self-hostable to eliminate TTS variable cost if Arabic support lands. |
| [Higgs Audio V2 / Orpheus / Fish Audio S2 / Dia2 / Piper](https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models/) | tts-open-source | self-hosted / free | free (self-host) | 2026 open-source TTS field for self-hosting (expressive dialogue, cloning, lightweight). All English/multilingual-leaning; none verified strong for Arabic. Watch for Arabic + word-timestamp support maturing. |
| [HeyGen (dubbing + avatars)](https://www.heygen.com/blog/best-ai-dubbing-tools) | dubbing-lipsync | api / paid | subscription tiers (paid); API on higher tiers | Won 2026 head-to-head dubbing tests; lip-synced video dubbing in 175+ languages with voice preservation; avatar/lipsync 40+ langs. Full video output (unlike ElevenLabs audio-only). Relevant only if project ever wants talking-head dubs; overkill for faceless/keep-picture paths. |
| [Rask AI](https://nesyona.com/articles/best-ai-dubbing-translation-tools-2026) | dubbing | api (enterprise) / paid | minute-based; Creator Pro $120/mo for lipsync | High-volume video localization, 130+ languages, minute-based pricing; lipsync locked behind Creator Pro $120/mo; API mostly enterprise. Web-UI-first. |
| [DeepDub](https://replacehumans.ai/best-ai-dubbing-platforms/) | dubbing | api (enterprise) | enterprise (contact sales) | Enterprise/broadcast-grade dubbing with emotion-aware synthesis; targets media production. Overkill/expensive for this project. |
| [Sync.so (Sync)](https://lipsync.com/compare/best-lip-sync-api) | lipsync-api | api / paid | usage-based (paid) | Pure, best-in-class lip-sync accuracy on real footage; strongest developer API (SDKs, webhooks); language-agnostic (works with Arabic audio). Only relevant if the dub path moves to lip-synced talking heads. |
| [D-ID](https://lipsync.com/compare/heygen-vs-d-id) | lipsync-api | api / paid | subscription (paid) | Animates still images into talking avatars; good webhook support; 40+ langs. Not needed for faceless/keep-picture but an option for avatar intros. |
| [LatentSync / Wav2Lip](https://lipsync.com/compare/wav2lip-vs-latentsync) | lipsync-open-source | self-hosted / free | free (self-host GPU) | Open-source diffusion (LatentSync) and classic (Wav2Lip) lip-sync; language-agnostic so Arabic audio works; self-hostable (Python/PyTorch/GPU). Zero variable cost lipsync if project ever needs it; setup complexity is the cost. |

## Key facts (as researched)

- ElevenLabs /v1/text-to-speech/{voice_id}/with-timestamps (and stream-with-timestamps) returns 'characters', 'character_start_times_seconds', 'character_end_times_seconds' arrays; default model eleven_multilingual_v2. This is the exact primitive the project groups into word timings for Pillow+raqm karaoke captions.
- Confirmed timestamp-capable ElevenLabs models: eleven_multilingual_v2 (29 langs, 10k char) and eleven_flash_v2_5 (32 langs, ~75ms, 40k char). eleven_turbo_v2_5 is DEPRECATED (use flash_v2_5).
- eleven_v3 = flagship expressive model, 70+ languages, 5,000-char cap. Native word/character-timestamp support on the standard with-timestamps endpoint is NOT clearly confirmed in ElevenLabs docs as of Aug 2026; third-party wrappers (WaveSpeed 'Eleven V3 Timing', Segmind) advertise v3 timing but that is not proof of the native endpoint. TREAT AS UNVERIFIED.
- ElevenLabs pricing Aug 2026: Creator $22/mo = 100k credits (~100 min TTS); Pro $99/mo = 500k credits; 1 credit ≈ 1 character; Creator API overage $0.30 / 1k chars; automatic dubbing ~2000 credits/min.
- ElevenLabs Scribe v2 STT gives precise word-level timestamps in 90+ langs (realtime ~150ms) — an alignment source independent of the TTS step.
- Cartesia Sonic-3 (Sonic 3.6): 44 languages incl Arabic, sub-100ms TTFB, word-level timestamps.
- Hume Octave 2 returns BOTH word- and phoneme-level timestamps in TTS responses.
- OpenAI gpt-4o-mini-tts (~$0.015/1k chars) has NO native word timestamps and English-optimized voices (weak Arabic) — not suitable for the Arabic karaoke path.
- Cheap timestamp-capable clouds for Arabic: Azure TTS ~$1/M chars (WordBoundary events; ar-AE/SA/EG/LB/OM locales), Amazon Polly ~$4/M chars (SpeechMarks word/viseme timing; MSA Zeina + Gulf ar-AE Hala/Zayd neural), Google Cloud TTS ~$4/M chars (SSML timepoints, ar-XA MSA only).
- Arabic-native Munsit/Faseeh: 25+ dialects incl Gulf/Levantine/Egyptian/Maghrebi + code-switching, WebSocket streaming <150ms, on-prem/VPC/on-device, from $8/mo — best Arabic dialect authenticity; caption-grade timestamp granularity undocumented (verify).
- Open-source TTS (Kokoro-82M Apache-2.0; Chatterbox/Chatterbox Turbo MIT 0.5B, beats ElevenLabs in listener-preference tests; Higgs Audio V2, Orpheus, Fish Audio S2, Dia2, Piper) is strong for English/self-hosting but Arabic support is weak/unverified across the board.
- Dubbing landscape: HeyGen won 2026 head-to-head (lipsync + 175+ langs, full video); ElevenLabs Dubbing v2 audio-only (90+ langs, BYO-transcript enterprise-only); Rask 130+ langs (lipsync behind $120/mo); DeepDub enterprise emotion-aware.
- Lipsync: Sync.so best pure-lipsync API (language-agnostic); D-ID for stills; open-source LatentSync (diffusion) and Wav2Lip are language-agnostic and self-hostable (GPU setup is the cost).

## Relevance to the video factory

FACELESS ARABIC PATH (karaoke captions): The project's dependence on per-character timestamps is well-served by staying on eleven_multilingual_v2 or eleven_flash_v2_5 via the existing /with-timestamps call — do NOT switch narration to eleven_v3 for expressiveness without first verifying it returns character timing on that endpoint, otherwise caption timing silently breaks (the existing verify_timing + align.py fallback would catch drift but not a missing-timestamps failure). Two concrete upgrades that fit the fixed-cost-first principle: (1) Azure TTS (~$1/M chars, WordBoundary events) or Amazon Polly (SpeechMarks, Gulf ar-AE neural voices) as a much cheaper timestamp-returning voice provider behind the same 'group char/word timings' logic — 20-30x cheaper than ElevenLabs; (2) Munsit/Faseeh if generic-MSA ElevenLabs voice quality is a weakness for a target dialect — but confirm its API exposes caption-grade word timing first. Cartesia Sonic-3 and Hume Octave 2 are drop-in-ish timestamp-returning alternatives worth A/B-ing for Arabic naturalness. Fully self-hosted zero-variable-cost TTS (Kokoro/Chatterbox) is not yet viable for Arabic. DUB PATH (keep picture, mute, overlay Arabic voice + burned captions): the current hand-rolled approach keeps control and stays cheap; ElevenLabs Dubbing v2 could replace it but is a black box and BYO-transcript is enterprise-only, so it fits less well than the existing pipeline. Scribe v2 (word-level STT) is the most useful new building block here — it can timestamp an already-produced Arabic voiceover to drive burned subtitles without re-running TTS. Lipsync (Sync.so / LatentSync) is irrelevant to faceless and keep-picture dubs, but LatentSync/Wav2Lip (self-hosted, language-agnostic) are the fallback if a talking-head dub variant is ever wanted.

## Watch list

- CONFIRM whether eleven_v3 returns character/word timestamps on the native /with-timestamps endpoint before ever switching narration off multilingual_v2/flash_v2_5 — this is the single highest-risk unknown for the karaoke caption path.
- Evaluate Azure TTS (WordBoundary, ~$1/M chars) and Amazon Polly (SpeechMarks, Gulf ar-AE neural) as drop-in cheaper timestamp providers behind the existing voice.py timing-grouping logic — potential 20-30x TTS cost cut.
- Test Munsit/Faseeh Arabic dialect quality vs ElevenLabs AND verify it exposes caption-grade word/char timing over its API.
- A/B Cartesia Sonic-3 and Hume Octave 2 for Arabic naturalness + timestamp fidelity as expressive alternatives.
- Track ElevenLabs Scribe v2 as an alignment source for the dub path (timestamp an existing voiceover for burned subtitles) — could simplify DUB.md tooling.
- Watch open-source TTS (Chatterbox multilingual, Fish Audio, Higgs) for real Arabic support — would enable zero-variable-cost self-hosted narration.
- Re-check ElevenLabs credit pricing and dubbing rates periodically (fast-moving); current Creator $22/100k, dubbing ~2000 credits/min.
- OpenAI TTS reported quality regressions in early 2026 and still no word timestamps — recheck only if it adds alignment output.

## Sources

- <https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps>
- <https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps>
- <https://elevenlabs.io/blog/new-text-to-speech-endpoints-with-timestamps>
- <https://elevenlabs.io/docs/overview/models>
- <https://www.webfuse.com/elevenlabs-cheat-sheet>
- <https://wavespeed.ai/models/elevenlabs/eleven-v3/timing>
- <https://flexprice.io/blog/elevenlabs-pricing-breakdown>
- <https://bigvu.tv/blog/elevenlabs-pricing-2026-plans-credits-commercial-rights-api-costs/>
- <https://elevenlabs.io/docs/overview/capabilities/dubbing>
- <https://elevenlabs.io/docs/eleven-api/guides/how-to/dubbing/bring-your-own-transcript>
- <https://munsit.com/blog/best-arabic-tts>
- <https://munsit.com/blog/lahajati-alternatives-2026-arabic-tts-platforms>
- <https://docs.cartesia.ai/build-with-cartesia/tts-models/latest>
- <https://dev.hume.ai/docs/text-to-speech-tts/timestamps>
- <https://developers.openai.com/api/docs/guides/text-to-speech>
- <https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026>
- <https://findskill.ai/blog/best-open-source-tts-2026/>
- <https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models/>
- <https://www.heygen.com/blog/best-ai-dubbing-tools>
- <https://nesyona.com/articles/best-ai-dubbing-translation-tools-2026>
- <https://lipsync.com/compare/best-lip-sync-api>
- <https://lipsync.com/compare/wav2lip-vs-latentsync>
- <https://www.pkgpulse.com/guides/elevenlabs-vs-openai-tts-vs-cartesia-text-to-speech-2026>
