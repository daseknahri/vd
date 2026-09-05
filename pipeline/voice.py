"""Voice stage: script.json -> voiceover.mp3 + timing.json.

One TTS request per scene, passing neighbor-scene text as previous_text /
next_text so prosody stays continuous across scene boundaries. Scene mp3s
are concatenated with the ffmpeg concat demuxer (re-encoded to one clean
stream). Scene start offsets come from ffprobe-measured durations of each
scene file — alignment end times include trailing silence and are never
trusted as durations.

Pronunciation overrides (pronunciation.json, display word -> spoken
respelling) are applied to the text sent to TTS only; timing.json carries
the display word so captions show the original spelling.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any, Protocol

import requests

from pipeline import contract, diacritize
from pipeline.contract import ContractError, ffmpeg_path, require_env
from pipeline.errors import StageError

STAGE = "voice"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
_TMP_DIR = "voice_tmp"  # scratch inside the project folder; removed on success
_CACHE_DIR = "voice_cache"  # persistent per-scene audio cache; NOT removed
VOICE_REPORT = "voice_report.json"  # stage-private usage record (chars sent)


class TTSProvider(Protocol):
    def synthesize(
        self, text: str, prev_text: str, next_text: str, *,
        style: dict[str, Any] | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Return (mp3 bytes, character alignment).

        `style` is an optional per-scene delivery override (e.g.
        {"exaggeration": 0.7, "cfg_weight": 0.35} for Chatterbox); providers
        that cannot act on it ignore it. It is part of the cache key, so two
        scenes with the same text but different delivery cache separately.

        Alignment shape: {"characters": [...],
                          "character_start_times_seconds": [...],
                          "character_end_times_seconds": [...]}
        """
        ...

    def signature(self) -> str:
        """Stable string of the settings that affect the output (voice id,
        model, voice settings). Part of the cache key so changing the voice
        or model invalidates cached audio."""
        ...


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _retry_after_seconds(resp: "requests.Response") -> int:
    """Parse a Retry-After header (delta-seconds form) into a non-negative int;
    0 when absent or unparseable. ElevenLabs sends it on 429/5xx overload."""
    try:
        return max(0, int(resp.headers.get("Retry-After", "0")))
    except (ValueError, TypeError):
        return 0


def _post_json(url: str, *, headers: dict, body: dict) -> dict:
    """POST with timeout + 3-attempt exponential backoff. 200 -> parsed JSON.
    On 429/503/529 the server's Retry-After (if larger) overrides the backoff,
    so we wait the rate-limit/overload window instead of hammering."""
    last_error = ""
    for attempt in range(3):
        backoff = 2 ** attempt
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise StageError(STAGE, f"non-JSON response from {url}: {exc}")
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                break  # bad key / bad request won't heal with retries
            backoff = max(backoff, _retry_after_seconds(resp))
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt < 2:
            time.sleep(backoff)
    raise StageError(STAGE, f"TTS request failed: {last_error}")


class ElevenLabsTTS:
    def __init__(self, api_key: str, voice_id: str, model_id: str,
                 stability: float, similarity_boost: float, speed: float):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.stability = stability
        self.similarity_boost = similarity_boost
        self.speed = speed

    def signature(self) -> str:
        # api_key deliberately excluded — it does not change the audio, and
        # keeping it out avoids leaking a secret into cache filenames.
        return json.dumps({
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "stability": self.stability,
            "similarity_boost": self.similarity_boost,
            "speed": self.speed,
        }, sort_keys=True)

    def synthesize(
        self, text: str, prev_text: str, next_text: str, *,
        style: dict[str, Any] | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        # `style` (Chatterbox exaggeration/cfg_weight) does not map onto
        # ElevenLabs voice_settings; per-scene emotion here would use v3 audio
        # tags in the text instead. Ignored so the interface stays uniform.
        body = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
                "speed": self.speed,
            },
            "previous_text": prev_text,
            "next_text": next_text,
        }
        data = _post_json(
            API_URL.format(voice_id=self.voice_id),
            headers={"xi-api-key": self.api_key},
            body=body,
        )
        try:
            audio = base64.b64decode(data["audio_base64"])
            alignment = data["alignment"]
            for key in ("characters", "character_start_times_seconds",
                        "character_end_times_seconds"):
                if not isinstance(alignment[key], list):
                    raise KeyError(key)
        except (KeyError, TypeError, binascii.Error) as exc:
            raise StageError(STAGE, f"malformed ElevenLabs response: {exc!r}")
        return audio, alignment


def _build_provider(cfg: dict, env: dict) -> TTSProvider:
    voice_cfg = cfg.get("voice")
    if not isinstance(voice_cfg, dict):
        raise ContractError("config: 'voice' section is required")
    name = str(voice_cfg.get("provider", "elevenlabs")).strip().lower()

    if name == "elevenlabs":
        voice_id = str(voice_cfg.get("voice_id") or "").strip()
        if not voice_id:
            raise ContractError(
                "config: voice.voice_id is empty — set your ElevenLabs voice id "
                "in config.yaml (or the project's project.yaml)"
            )
        api_key = require_env(env, "ELEVENLABS_API_KEY", "ElevenLabs TTS (voice stage)")
        return ElevenLabsTTS(
            api_key=api_key,
            voice_id=voice_id,
            model_id=voice_cfg.get("model_id", "eleven_multilingual_v2"),
            stability=float(voice_cfg.get("stability", 0.5)),
            similarity_boost=float(voice_cfg.get("similarity_boost", 0.75)),
            speed=float(voice_cfg.get("speed", 1.0)),
        )

    if name == "chatterbox":
        # Self-hosted open TTS (fixed cost). Needs no ElevenLabs key/voice_id;
        # word timing comes from WhisperX forced alignment inside the provider.
        # Lazy import so the pipeline venv never hard-depends on it.
        from pipeline import chatterbox_tts
        return chatterbox_tts.build(voice_cfg, env)

    if name == "silma":
        # Reliable self-hosted Arabic TTS (its own venv). Diacritizes internally;
        # alignment via the pipeline's faster-whisper (transcribe.*).
        from pipeline import silma_tts
        return silma_tts.build(voice_cfg, env, cfg.get("transcribe"))

    raise ContractError(
        f"config: voice.provider '{name}' is not implemented "
        f"(supported: 'elevenlabs', 'chatterbox', 'silma')"
    )


# --------------------------------------------------------------------------
# Pronunciation overrides (spoken text only; display text untouched)
# --------------------------------------------------------------------------

def _strip_edge_punct(token: str) -> tuple[str, str, str]:
    start, end = 0, len(token)
    while start < end and unicodedata.category(token[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(token[end - 1]).startswith("P"):
        end -= 1
    return token[:start], token[start:end], token[end:]


def _spoken_word(token: str, overrides: dict[str, str]) -> str:
    if token in overrides:
        return overrides[token]
    # Overrides are keyed on bare words; keep punctuation stuck to the token
    # (Arabic comma, period...) attached around the respelling.
    lead, core, trail = _strip_edge_punct(token)
    if core and core in overrides:
        return lead + overrides[core] + trail
    return token


def _spoken_text(display: str, overrides: dict[str, str],
                 diacritized: str | None = None) -> str:
    """The exact text sent to the TTS. Layers, in order of precedence:
    1. pronunciation.json overrides (win — proper nouns/loanwords the diacritizer
       mangles, e.g. فيكتور/فرانكل), matched on the plain display word;
    2. CATT auto-diacritization (`diacritized`, same word count as display) for
       every other word — its harakat make the TTS pronounce correctly;
    3. the plain word, when neither applies.
    Original punctuation is re-attached (CATT drops it) so pacing cues survive.
    Display/caption text is never touched, so the caption/timing 1:1 map holds."""
    display_words = display.split()
    dia_words: list[str] | None = None
    if isinstance(diacritized, str):
        dw = diacritized.split()
        if len(dw) == len(display_words):  # must align 1:1 or we don't use it
            dia_words = dw
    spoken_words = []
    for i, token in enumerate(display_words):
        if token in overrides:
            spoken = overrides[token]
        else:
            lead, core, trail = _strip_edge_punct(token)
            if core and core in overrides:
                spoken = lead + overrides[core] + trail
            elif dia_words is not None:
                # CATT diacritized this token and stripped its punctuation; take
                # the diacritized core and re-attach the original punctuation.
                _dl, dcore, _dt = _strip_edge_punct(dia_words[i])
                spoken = lead + (dcore or dia_words[i]) + trail
            else:
                spoken = token
        # Word-for-word substitution is the contract: caption timing maps
        # spoken word N back onto display word N.
        if len(spoken.split()) != 1:
            raise ContractError(
                f"pronunciation/diacritization for {token!r} produced "
                f"{spoken!r} — must be exactly one word"
            )
        spoken_words.append(spoken)
    return " ".join(spoken_words)


def scene_characters(
    script: dict[str, Any], overrides: dict[str, str]
) -> list[tuple[int, int]]:
    """Billable characters per scene: the length of the exact spoken text
    sent to ElevenLabs as `text`. previous_text/next_text conditioning is
    NOT billed, so it is excluded. Reused by `run.py estimate` so the
    prediction is the same string the stage actually sends — it can never
    drift from what gets charged. Raises ContractError on a bad
    pronunciation override (the same failure the voice stage would hit)."""
    return [
        (scene["id"], len(_spoken_text(scene["narration_ar"].strip(), overrides)))
        for scene in script["scenes"]
    ]


# --------------------------------------------------------------------------
# Per-scene audio cache (content-addressed; avoids re-billing unchanged scenes)
# --------------------------------------------------------------------------

def _cache_key(signature: str, text: str, prev_text: str,
               next_text: str, style: dict[str, Any] | None = None) -> str:
    """Hash of everything that determines the TTS output. Same request ->
    same key -> reuse the stored audio, no new API call. Neighbor text is
    included because it conditions prosody, so editing one scene correctly
    invalidates its neighbors (not the whole video). Per-scene `style`
    (delivery params) is included so re-emotioning a scene re-synthesizes it."""
    payload = json.dumps(
        {"sig": signature, "text": text, "prev": prev_text, "next": next_text,
         "style": style or None},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _synthesize_cached(
    provider: TTSProvider, cache_dir: Path, signature: str,
    text: str, prev_text: str, next_text: str,
    style: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any], bool]:
    """(audio, alignment, from_cache). A cache hit costs nothing; a miss
    calls the provider and stores the result. To re-roll audio for identical
    text, delete the voice_cache/ folder."""
    key = _cache_key(signature, text, prev_text, next_text, style)
    mp3_path = cache_dir / f"{key}.mp3"
    meta_path = cache_dir / f"{key}.json"
    if mp3_path.exists() and meta_path.exists():
        try:
            alignment = json.loads(meta_path.read_text(encoding="utf-8"))
            return mp3_path.read_bytes(), alignment, True
        except (ValueError, OSError):
            pass  # corrupt/partial cache entry -> fall through and re-synthesize
    audio, alignment = provider.synthesize(text, prev_text, next_text, style=style)
    mp3_path.write_bytes(audio)
    meta_path.write_text(json.dumps(alignment, ensure_ascii=False),
                         encoding="utf-8")
    return audio, alignment, False


# --------------------------------------------------------------------------
# Alignment -> word timings
# --------------------------------------------------------------------------

def _words_from_alignment(
    display_text: str, alignment: dict[str, Any], offset: float
) -> list[dict[str, Any]]:
    """Group character timestamps into words; label them with DISPLAY words."""
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    spans: list[tuple[float, float]] = []
    cur_start: float | None = None
    cur_end = 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur_start is not None:
                spans.append((cur_start, cur_end))
                cur_start = None
        else:
            if cur_start is None:
                cur_start = s
            cur_end = e
    if cur_start is not None:
        spans.append((cur_start, cur_end))

    display_words = display_text.split()
    if len(spans) != len(display_words):
        raise StageError(
            STAGE,
            f"alignment yielded {len(spans)} words but narration has "
            f"{len(display_words)} — provider alignment is unusable",
        )
    return [
        {"word": w, "start": round(offset + s, 3), "end": round(offset + e, 3)}
        for w, (s, e) in zip(display_words, spans)
    ]


# --------------------------------------------------------------------------
# ffmpeg helpers (kept module-level so tests can patch them)
# --------------------------------------------------------------------------

def _probe_duration(path: Path) -> float:
    cmd = [
        ffmpeg_path("ffprobe"), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    # Explicit encoding: Windows locale codepages choke (strict
    # UnicodeDecodeError) on UTF-8 bytes in ffprobe/ffmpeg output.
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise StageError(STAGE, f"ffprobe failed on {path.name}: "
                                f"{proc.stderr.strip()[:300]}")
    try:
        duration = float(proc.stdout.strip())
    except ValueError:
        raise StageError(STAGE, f"ffprobe gave no duration for {path.name}")
    if duration <= 0:
        raise StageError(STAGE, f"{path.name} has zero duration")
    return duration


def _quote_concat(path: Path) -> str:
    # concat demuxer wants forward slashes + single quotes (even on
    # Windows); embedded apostrophes must be escaped or they truncate the
    # file directive (same escaping as render_ffmpeg).
    return path.as_posix().replace("'", r"'\''")


def _concat_mp3s(scene_paths: list[Path], out_path: Path, workdir: Path) -> None:
    list_path = workdir / "concat.txt"
    # Absolute paths: the concat demuxer resolves relative `file` entries against
    # the concat.txt's own directory, which doubles a project-relative path
    # (voice_tmp/projects/.../voice_tmp/...). Absolute paths are unambiguous.
    list_path.write_text(
        "".join(f"file '{_quote_concat(p.resolve())}'\n" for p in scene_paths),
        encoding="utf-8",
    )
    cmd = [
        ffmpeg_path("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-codec:a", "libmp3lame", "-ar", "48000", "-b:a", "192k",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise StageError(STAGE, f"ffmpeg concat failed: "
                                f"{proc.stderr.strip()[:500]}")


# --------------------------------------------------------------------------
# Per-scene expressive delivery (Chatterbox) + designed inter-scene pauses.
# Opt-in: with no `voice.delivery` config the whole feature is inert and the
# stage behaves exactly as before (one global voice, no pauses).
# --------------------------------------------------------------------------

def _delivery_for_scene(
    scene: dict[str, Any], next_mood: str | None, dcfg: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, float]:
    """Map a scene's `mood` to (style, pause_after) from `voice.delivery`.

    style = per-scene TTS delivery override (Chatterbox exaggeration/cfg_weight)
    or None when delivery is unconfigured. pause_after = seconds of silence to
    fold in AFTER the scene (a breath), bumped when the next scene changes mood
    (a section break) and capped at `max_pause`. Returns (None, 0.0) when
    delivery is not configured, so the stage is unchanged by default."""
    if not dcfg:
        return None, 0.0
    by_mood = dcfg.get("by_mood") or {}
    params = by_mood.get(scene.get("mood")) or dcfg.get("default") or {}
    style = {}
    if "exaggeration" in params:
        style["exaggeration"] = float(params["exaggeration"])
    if "cfg_weight" in params:
        style["cfg_weight"] = float(params["cfg_weight"])
    pause = float(params.get("pause_after", 0.0))
    shift = float(dcfg.get("mood_shift_pause", 0.0))
    if shift and next_mood is not None and next_mood != scene.get("mood"):
        pause = max(pause, shift)
    pause = min(pause, float(dcfg.get("max_pause", 2.5)))
    return (style or None), max(0.0, pause)


def _append_silence(path: Path, seconds: float) -> None:
    """Re-encode `path` in place with `seconds` of trailing silence (a designed
    pause). Applied AFTER the TTS cache, so tuning pauses never re-bills audio;
    also normalizes the clip to 48k mono so concat inputs stay uniform."""
    if seconds <= 0:
        return
    tmp = path.with_suffix(".pad.mp3")
    cmd = [
        ffmpeg_path("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-af", f"apad=pad_dur={seconds:.3f}",
        "-codec:a", "libmp3lame", "-ar", "48000", "-ac", "1", "-b:a", "192k",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise StageError(STAGE, f"pause padding failed on {path.name}: "
                                f"{proc.stderr.strip()[:300]}")
    import os
    os.replace(tmp, path)


def _rambled(raw_seconds: float, word_count: int) -> bool:
    """True when a take's audio is far longer than the script could fill even at
    a slow ~1.4 words/sec — i.e. the TTS looped / over-generated. Heavy Arabic
    diacritization is out-of-distribution for Chatterbox and triggers this on some
    scenes (28-40s of audio for an 8s script); the scene is then redone with its
    plain text, which is stable."""
    return word_count > 0 and raw_seconds > word_count / 1.4 + 2.5


# --------------------------------------------------------------------------
# Public, stable aliases for reuse by the dub workflow (pipeline/dub.py) and
# tests. The underscore versions remain the implementation; import these so
# the dub path never reaches into private voice internals.
# --------------------------------------------------------------------------
build_provider = _build_provider
synthesize_cached = _synthesize_cached
probe_duration = _probe_duration
words_from_alignment = _words_from_alignment
# Reused by the voice-content audit (pipeline/verify_voice.py) to reconstruct a
# scene's exact cache key + delivery so it can re-roll one stuttering take
# without disturbing the others.
spoken_text = _spoken_text
cache_key = _cache_key
delivery_for_scene = _delivery_for_scene
CACHE_DIR = _CACHE_DIR


# --------------------------------------------------------------------------
# Stage entry point
# --------------------------------------------------------------------------

def run(project: contract.Project, cfg: dict, env: dict, *,
        force: bool = False) -> None:
    if (not force and project.has(contract.VOICEOVER)
            and project.has(contract.TIMING)):
        return
    if not project.has(contract.SCRIPT):
        # Missing contracted input = contract violation (consistent with
        # ingest/render).
        raise ContractError(
            f"{contract.SCRIPT} not found — run the script stage first"
        )
    script = project.script()
    provider = _build_provider(cfg, env)
    voice_cfg = cfg.get("voice") or {}
    try:
        _synthesize_project(project, script, provider, voice_cfg)
    finally:
        # Release any GPU/worker the provider holds (e.g. the Chatterbox worker
        # keeps ~3 GB of VRAM resident) so the next stage — generated B-roll on
        # the same 8 GB GPU — isn't starved. No-op for ElevenLabs (no close()).
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def _synthesize_project(project: contract.Project, script: dict,
                        provider: TTSProvider,
                        voice_cfg: dict[str, Any] | None = None) -> None:
    overrides = project.pronunciation_overrides()
    scenes = script["scenes"]
    narrations = [s["narration_ar"].strip() for s in scenes]
    # Auto-diacritize (CATT) so the TTS pronounces correctly; best-effort and
    # per-scene, falling back to plain text where unavailable. Overrides + display
    # spelling are handled inside _spoken_text.
    provider_name = str((voice_cfg or {}).get("provider", "")).strip().lower()
    if provider_name == "silma":
        # SILMA diacritizes internally (CATT) and is stable — send plain text and
        # skip our diacritization + ramble guard (both Chatterbox-only workarounds).
        spoken = list(narrations)
        spoken_plain = spoken
        ramble_guard = False
    else:
        diacritize_on = (voice_cfg or {}).get("diacritize", True)
        diacritized = (diacritize.diacritize_batch(narrations)
                       if diacritize_on else [None] * len(narrations))
        spoken = [_spoken_text(n, overrides, diacritized[i])
                  for i, n in enumerate(narrations)]
        # Plain (undiacritized) spoken text per scene — the ramble guard's fallback.
        spoken_plain = [_spoken_text(n, overrides) for n in narrations]
        ramble_guard = diacritize_on and (voice_cfg or {}).get("ramble_guard", True)
    delivery_cfg = (voice_cfg or {}).get("delivery")

    tmp_dir = project.path(_TMP_DIR)
    tmp_dir.mkdir(exist_ok=True)
    cache_dir = project.path(_CACHE_DIR)
    cache_dir.mkdir(exist_ok=True)
    signature = provider.signature()

    scene_files: list[Path] = []
    timing_scenes: list[dict[str, Any]] = []
    used_texts: list[str] = []
    fell_back: list[int] = []
    billed = 0
    offset = 0.0
    for i, scene in enumerate(scenes):
        prev_text = spoken[i - 1] if i > 0 else ""
        next_text = spoken[i + 1] if i < len(scenes) - 1 else ""
        next_mood = scenes[i + 1].get("mood") if i < len(scenes) - 1 else None
        style, pause_after = _delivery_for_scene(scene, next_mood, delivery_cfg)
        scene_path = tmp_dir / f"scene_{scene['id']:03d}.mp3"

        text_i = spoken[i]
        audio, alignment, from_cache = _synthesize_cached(
            provider, cache_dir, signature, text_i, prev_text, next_text, style)
        scene_path.write_bytes(audio)
        # Ramble guard: if a DIACRITIZED take over-generates, redo the scene with
        # its plain text (stable). Measured on the raw take, before the pause.
        if (ramble_guard and text_i != spoken_plain[i]
                and _rambled(_probe_duration(scene_path),
                             len(narrations[i].split()))):
            text_i = spoken_plain[i]
            audio, alignment, from_cache = _synthesize_cached(
                provider, cache_dir, signature, text_i, prev_text, next_text,
                style)
            scene_path.write_bytes(audio)
            fell_back.append(scene["id"])
        used_texts.append(text_i)
        if not from_cache:
            billed += len(text_i)  # only real API calls are billed
        # Words are timed against the SPOKEN audio (offset); the pause is
        # trailing silence folded into the scene so timing.json stays
        # contiguous and the render/captions never drift.
        words = _words_from_alignment(narrations[i], alignment, offset)
        _append_silence(scene_path, pause_after)
        duration = _probe_duration(scene_path)
        timing_scenes.append({
            "id": scene["id"],
            "start": round(offset, 3),
            "end": round(offset + duration, 3),
            "words": words,
        })
        offset += duration
        scene_files.append(scene_path)

    _concat_mp3s(scene_files, project.path(contract.VOICEOVER), tmp_dir)
    timing = {"total_seconds": round(offset, 3), "scenes": timing_scenes}
    contract.validate_timing(timing)
    project.write_json(contract.TIMING, timing)
    # Record TTS usage (chars = ElevenLabs billing unit): total is the whole
    # script; billed excludes scenes served from the cache this run, so spend
    # is auditable after the fact and matches `run.py estimate` on a cold run.
    project.write_json(VOICE_REPORT, {
        "total_characters": sum(len(s) for s in used_texts),
        "billed_characters": billed,
        "diacritized_fallback_scenes": fell_back,
        "scenes": [{"id": sc["id"], "characters": len(sp)}
                   for sc, sp in zip(scenes, used_texts)],
        "note": "billed characters = `text` only; previous_text/next_text "
                "conditioning is not billed by ElevenLabs; cache hits are "
                "excluded from billed_characters; diacritized_fallback_scenes "
                "over-generated on tashkeel and were redone with plain text",
    })
    shutil.rmtree(tmp_dir, ignore_errors=True)
