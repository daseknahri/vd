# Captions, subtitles & Arabic RTL

> **Research snapshot.** Compiled by a web-research sweep for the video-factory project. This is a fast-moving field: prices, versions and availability change monthly. Treat specifics as *leads to verify*, not gospel — follow the sources. Re-run the `ai-video-field-research` workflow to refresh.

## Summary

As of Aug 2026 the consumer "viral caption" tools (Submagic, Captions.ai, CapCut, Veed, Zubtitle) all produce excellent English word-by-word/karaoke captions, but Arabic RTL remains their weak point: Submagic's own 2026 reviews call its Arabic/Hebrew/Urdu/Persian rendering "effectively broken — reversed text, disconnected letters," and RTL highlight-direction bugs are still being filed against other tools. This directly vindicates the video-factory decision to render captions itself with a real HarfBuzz shaper rather than trust a SaaS or a subtitle player. The self-hosted state of the art for Arabic RTL karaoke is: get word timestamps (ElevenLabs with-timestamps, or a forced aligner), then image-render each frame with genuine HarfBuzz shaping (Pillow+libraqm, exactly what the project does) and overlay as PNGs — sidestepping every player/libass shaping inconsistency. The libass/Windows story has shifted: modern Windows ffmpeg builds (gyan.dev "essentials," BtbN, Aug 2026) now bundle libharfbuzz, so burned libass Arabic can shape correctly where it once produced tofu — but RTL bidi/karaoke edge cases persist, so the project's ban on libass-for-Arabic is still defensible while worth re-testing. On alignment, WhisperX + wav2vec2 remains the popular word-timestamp path, but for Arabic specifically an MMS/CTC aligner (ctc-forced-aligner with "ara") or ElevenLabs' new Forced Alignment API (150+ languages) are stronger, and the latter is the natural fit for the dub path where you already have audio + a transcript.

## Tools & models

| Name | Category | Access | Pricing | Notable capability |
|------|----------|--------|---------|--------------------|
| [Submagic](https://www.submagic.co/ai-caption) | auto-caption / karaoke SaaS | paid (freemium) | Free (3 vids/mo, watermark); Starter $20/mo (30 vids); Pro $40/mo (100); Agency $80/mo (300); Magic Clips add-on ~$12/mo | Strongest animated word-by-word/karaoke caption output in the category (35+ styles, keyword highlight, 99% English accuracy) — but Arabic/Hebrew/Urdu/Persian RTL rendering is confirmed broken in 2026 (reversed text, disconnected letters). Not usable for Arabic. |
| [Captions.ai (Captions app)](https://cutsnap.ai/blog/submagic-vs-captions-ai) | auto-caption / AI video SaaS | paid (freemium) | freemium; paid tiers ~$10-25/mo range | Word-highlight captions + AI editing/avatars; strong for English short-form. RTL/Arabic precision weak, same category limitation as Submagic. |
| [CapCut auto-captions](https://www.capcut.com/resource/translate-videos-to-arabic) | auto-caption (editor) | free / freemium | free tier; CapCut Pro ~$9.99/mo | Auto-captions across 30+ languages, bilingual caption support (e.g. spoken English + Arabic), no watermark on captions. Reliable mainly for English/major languages; Arabic quality inconsistent. |
| [VEED](https://www.veed.io/tools/auto-subtitle-generator-online/subtitles-arabic) | auto-subtitle SaaS | freemium | free (watermark); paid from ~$18/mo | Auto Arabic subtitles hard-burned into video in seconds; free tier watermarked. Convenience tool, not karaoke-grade RTL control. |
| [Zubtitle](https://autosubtitles.com/alternatives/zubtitle) | short-form burned captions SaaS | freemium | free (1 vid/mo); paid from ~$19/mo | Upload → burned auto-captions with IG/TikTok styling presets. Free tier 1 video/mo, watermarked. |
| [ChatCut](https://chatcut.io/blog/how-to-add-subtitles-to-video-2026) | caption SaaS (RTL-aware) | paid (freemium) | unknown (freemium) | Exposes 20+ caption properties incl. text direction and RTL alignment for Arabic, active-word highlight color/radius/padding — one of the few SaaS explicitly advertising RTL karaoke controls in 2026. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | ASR + word timestamps (open source) | self-hosted / free | free (open source) | CTranslate2 Whisper; fast transcription with word-level timestamps. Already the project's ingest transcriber. Word timings usable but coarser than a dedicated forced aligner. |
| [WhisperX](https://github.com/m-bain/whisperX) | ASR + forced-alignment word timestamps (open source) | self-hosted / free | free (open source) | faster-whisper + VAD + wav2vec2 forced alignment (+ diarization) for accurate word timestamps. Arabic alignment falls back to jonatasgrosman/wav2vec2-large-xlsr-53-arabic; workable but not Arabic-tuned. |
| [ctc-forced-aligner (MahmoudAshraf97)](https://github.com/MahmoudAshraf97/ctc-forced-aligner) | forced alignment (open source) | self-hosted / free | free (open source) | CTC forced alignment on HF models incl. MMS/Wav2Vec2/HuBERT with native Arabic support (--language ara, handles Arabic script/romanization internally). Better Arabic word-timing than WhisperX's default aligner for the project's align.py fallback. |
| [Montreal Forced Aligner (MFA)](https://arxiv.org/pdf/2606.18466) | forced alignment (open source) | self-hosted / free | free (open source) | Classic phoneme/HMM forced aligner; needs an Arabic acoustic model + pronunciation dictionary. High precision but heavier setup than CTC/MMS aligners; 2026 surveys still treat it as a reference baseline. |
| [ElevenLabs Forced Alignment API](https://elevenlabs.io/docs/overview/capabilities/forced-alignment) | forced alignment (API) | api / paid | usage-based (ElevenLabs credits); exact per-char rate unverified | audio + transcript → precise per-word AND per-character timestamps; retrained on 150+ languages incl. Arabic (SA/UAE). Ideal for the DUB path (you already have source audio + Arabic translation) and as a high-quality align fallback. Char-level output maps cleanly to karaoke. |
| [ElevenLabs TTS with-timestamps](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps) | TTS + word/char timing (API) | api / paid | per-character TTS pricing (Creator/Pro tiers) | POST /v1/text-to-speech/{voice}/with-timestamps returns character timestamps grouped into word timings — the project's caption timing source for the faceless path. Only recurring variable cost. |
| [Pillow + libraqm](https://github.com/HOST-Oman/libraqm) | image-based caption rendering (open source) | self-hosted / free | free (open source) | Pillow's raqm layout engine = real HarfBuzz shaping + FriBidi bidi, rendering Arabic to PNGs with correct connected forms. The project's caption engine and the recommended best-practice for Arabic RTL karaoke: full per-word control, decoupled from any player/libass shaping bug. |
| [libass (ffmpeg subtitles filter)](https://github.com/libass/libass/pull/441) | burned ASS/SRT subtitle renderer | self-hosted / free | free (open source) | Renders ASS incl. \k karaoke. Uses HarfBuzz for shaping + FriBidi for bidi WHEN built with HarfBuzz. Modern Windows ffmpeg builds now bundle libharfbuzz, so Arabic can shape correctly — but RTL karaoke/bidi edge cases (reversed highlight order, VSFilter-vs-Uniscribe differences) persist. Project bans it for Arabic; still worth periodic re-test. |
| [HarfBuzz](https://en.wikipedia.org/wiki/HarfBuzz) | text shaping engine (open source) | self-hosted / free | free (open source) | The shaping engine under libraqm, browsers, and (when linked) libass. v14.2.0 (Apr 20 2026). Correct Arabic contextual joining depends on it; anything without it produces tofu/isolated forms. |
| [Motion Canvas / Remotion](https://www.wireflow.ai/blog/best-remotion-alternatives-in-2026) | programmatic/browser video rendering | self-hosted / free (Remotion has commercial license) | open source; Remotion needs paid license for larger teams | Code-driven video in the browser — text shaping goes through the browser's HarfBuzz, so Arabic RTL karaoke renders correctly. Alternative to Pillow+ffmpeg for caption compositing, at the cost of running a headless browser render farm. |
| [videodubbing.com RTL Subtitle Fixer](https://videodubbing.com/tools/rtl-subtitle-fixer/) | RTL SRT/VTT repair utility | free web tool | free | Fixes RTL ordering/shaping in Arabic/Hebrew/Persian SRT & VTT files for players that mishandle bidi. Useful for exporting a portable captions.srt/ass that displays correctly in third-party editors (e.g. CapCut handoff). |

## Key facts (as researched)

- Submagic 2026 pricing: Free (3 vids/mo, watermark), Starter $20/mo (30), Pro $40/mo (100), Agency $80/mo (300); Magic Clips add-on ~$12/mo. Advertises karaoke/word-by-word + keyword highlight, ~99% English accuracy, 48+ languages.
- Submagic's Arabic/Hebrew/Urdu/Persian rendering is confirmed BROKEN in multiple 2026 reviews: reversed text, disconnected letters. Explicit advice: do not use it if you publish in RTL languages.
- RTL highlight-direction bugs are still live in 2026 (e.g. ArchiveTune issue #485, Apr 2026: synced-lyric highlight animation reversed for Arabic) — karaoke word-order is a recurring RTL failure mode across tools.
- HarfBuzz stable is 14.2.0 (2026-04-20). Correct Arabic contextual joining requires it; without HarfBuzz, isolated/final forms render as tofu.
- Windows ffmpeg builds have changed: gyan.dev 'essentials' (release 9.0.1, 2026-08-12; git 2026-08-27) and BtbN (latest auto-build 2026-08-29) now list libharfbuzz among bundled libraries — so libass in these builds is linked with HarfBuzz and can shape Arabic. This challenges the project's premise that Windows libass ships without HarfBuzz.
- Even with HarfBuzz linked, libass RTL still has documented bidi/compatibility edge cases (VSFilter/Uniscribe vs HarfBuzz WHOLE_TEXT_LAYOUT; PR #441 adds ASS_FEATURE_WHOLE_TEXT_LAYOUT). Image-based PNG captions avoid all of it.
- ElevenLabs shipped a standalone Forced Alignment API (announced 2026) retrained on 150+ languages; returns word- AND character-level timestamps from audio + transcript; supports Arabic (SA/UAE). Distinct from TTS with-timestamps.
- For self-hosted Arabic word alignment, ctc-forced-aligner supports Arabic natively via `--language ara` with MMS/wav2vec2/HuBERT models; generally better for Arabic script than WhisperX's default wav2vec2-xlsr aligner.
- WhisperX = faster-whisper + VAD + wav2vec2 forced alignment (+ diarization); marketed ~70x realtime with batching; word-timing precision materially better than raw Whisper (e.g. ~93% vs ~85% on telephone speech).
- Pillow+libraqm gives genuine HarfBuzz+FriBidi shaping in Python and is the reliable self-hosted way to render Arabic RTL karaoke frames — the approach the project already uses.

## Relevance to the video factory

Both pipeline paths are validated by this research. FACELESS path: the project's core bet — drive Pillow+raqm RTL karaoke from ElevenLabs with-timestamps and overlay PNGs, never libass — is exactly the 2026 state of the art for Arabic, and the market gap is real: Submagic/Captions.ai (the best English karaoke tools) render Arabic reversed and disconnected, so there is no SaaS shortcut that would beat the in-house engine. Hard Rule 3 (no libass for Arabic) should be KEPT but its stated justification is now partly stale: modern gyan/BtbN Windows builds bundle libharfbuzz, so 'Windows libass has no HarfBuzz' is no longer strictly true — recommend a quick re-verification test (burn a Tajawal/Cairo Arabic sample through the current build's subtitles filter and inspect real frames) and, if it still misbehaves, update the rule's wording to cite the live RTL karaoke/bidi edge cases rather than a missing HarfBuzz. DUB path: ElevenLabs' new Forced Alignment API (audio+transcript → word/char timestamps, Arabic-supported) is the natural upgrade for aligning the Arabic voiceover to burned captions, and for the align.py fallback, ctc-forced-aligner (`--language ara`, MMS) is a stronger self-hosted Arabic aligner than WhisperX's default. For portable ASS/SRT exports handed to humans/CapCut, an RTL subtitle fixer avoids third-party bidi mangling. Net: no architecture change needed; refresh Hard Rule 3's rationale, consider the ElevenLabs Forced Alignment API for the dub/repair-timing path, and keep Pillow+raqm as the caption renderer.

## Watch list

- Re-verify Hard Rule 3: burn an Arabic sample through the CURRENT gyan/BtbN Windows ffmpeg subtitles filter (now bundling libharfbuzz) and inspect real frames — confirm whether tofu is gone and whether RTL \k karaoke highlight order is still wrong.
- ElevenLabs Forced Alignment API: confirm exact pricing (per-character/credit) and Arabic accuracy vs the existing with-timestamps flow before wiring it into the dub/repair-timing path.
- ctc-forced-aligner vs WhisperX for Arabic: benchmark word-boundary accuracy on real project audio to decide the align.py fallback model.
- libass RTL bidi work (PR #441 / ASS_FEATURE_WHOLE_TEXT_LAYOUT) — track whether upstream fully fixes RTL karaoke ordering, which could eventually make burned-ASS a viable portable path.
- SaaS RTL parity: watch whether Submagic/Captions.ai/ChatCut fix Arabic RTL karaoke rendering in a 2026 update (currently broken/limited) — would change the build-vs-buy calculus.
- HarfBuzz releases past 14.2.0 and Pillow/raqm version pins on Windows (raqm availability is the project's known cross-machine fragility).

## Sources

- <https://www.submagic.co/ai-caption>
- <https://coldiq.com/tools/submagic>
- <https://skybreakai.com/blog/submagic-review-2026>
- <https://cutsnap.ai/blog/submagic-vs-captions-ai>
- <https://chatcut.io/blog/how-to-add-subtitles-to-video-2026>
- <https://www.capcut.com/resource/translate-videos-to-arabic>
- <https://www.veed.io/tools/auto-subtitle-generator-online/subtitles-arabic>
- <https://autosubtitles.com/alternatives/zubtitle>
- <https://github.com/rukamori/ArchiveTune/issues/485>
- <https://en.wikipedia.org/wiki/HarfBuzz>
- <https://www.gyan.dev/ffmpeg/builds/>
- <https://github.com/BtbN/FFmpeg-Builds/releases>
- <https://github.com/libass/libass/pull/441>
- <https://github.com/libass/libass/issues/226>
- <https://elevenlabs.io/docs/overview/capabilities/forced-alignment>
- <https://elevenlabs.io/docs/api-reference/forced-alignment/create>
- <https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps>
- <https://github.com/m-bain/whisperX>
- <https://github.com/MahmoudAshraf97/ctc-forced-aligner>
- <https://modal.com/blog/choosing-whisper-variants>
- <https://arxiv.org/pdf/2606.18466>
- <https://videodubbing.com/tools/rtl-subtitle-fixer/>
- <https://www.wireflow.ai/blog/best-remotion-alternatives-in-2026>
