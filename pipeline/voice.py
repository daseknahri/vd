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
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any, Protocol

import requests

from pipeline import contract
from pipeline.contract import ContractError, ffmpeg_path, require_env
from pipeline.errors import StageError

STAGE = "voice"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
_TMP_DIR = "voice_tmp"  # scratch inside the project folder; removed on success


class TTSProvider(Protocol):
    def synthesize(
        self, text: str, prev_text: str, next_text: str
    ) -> tuple[bytes, dict[str, Any]]:
        """Return (mp3 bytes, character alignment).

        Alignment shape: {"characters": [...],
                          "character_start_times_seconds": [...],
                          "character_end_times_seconds": [...]}
        """
        ...


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _post_json(url: str, *, headers: dict, body: dict) -> dict:
    """POST with timeout + 3-attempt exponential backoff. 200 -> parsed JSON."""
    last_error = ""
    for attempt in range(3):
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
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt < 2:
            time.sleep(2 ** attempt)
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

    def synthesize(
        self, text: str, prev_text: str, next_text: str
    ) -> tuple[bytes, dict[str, Any]]:
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
    voice_id = str(voice_cfg.get("voice_id") or "").strip()
    if not voice_id:
        raise ContractError(
            "config: voice.voice_id is empty — set your ElevenLabs voice id "
            "in config.yaml (or the project's project.yaml)"
        )
    name = voice_cfg.get("provider", "elevenlabs")
    if name != "elevenlabs":
        raise ContractError(
            f"config: voice.provider '{name}' is not implemented "
            f"(only 'elevenlabs')"
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


def _spoken_text(display: str, overrides: dict[str, str]) -> str:
    display_words = display.split()
    spoken_words = []
    for token in display_words:
        spoken = _spoken_word(token, overrides)
        # Word-for-word substitution is the contract: caption timing maps
        # spoken word N back onto display word N.
        if len(spoken.split()) != 1:
            raise ContractError(
                f"pronunciation override for {token!r} produced {spoken!r} — "
                f"respellings must be exactly one word"
            )
        spoken_words.append(spoken)
    return " ".join(spoken_words)


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
    list_path.write_text(
        "".join(f"file '{_quote_concat(p)}'\n" for p in scene_paths),
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
    _synthesize_project(project, script, provider)


def _synthesize_project(project: contract.Project, script: dict,
                        provider: TTSProvider) -> None:
    overrides = project.pronunciation_overrides()
    scenes = script["scenes"]
    narrations = [s["narration_ar"].strip() for s in scenes]
    spoken = [_spoken_text(n, overrides) for n in narrations]

    tmp_dir = project.path(_TMP_DIR)
    tmp_dir.mkdir(exist_ok=True)
    scene_files: list[Path] = []
    timing_scenes: list[dict[str, Any]] = []
    offset = 0.0
    for i, scene in enumerate(scenes):
        prev_text = spoken[i - 1] if i > 0 else ""
        next_text = spoken[i + 1] if i < len(scenes) - 1 else ""
        audio, alignment = provider.synthesize(spoken[i], prev_text, next_text)
        scene_path = tmp_dir / f"scene_{scene['id']:03d}.mp3"
        scene_path.write_bytes(audio)
        words = _words_from_alignment(narrations[i], alignment, offset)
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
    shutil.rmtree(tmp_dir, ignore_errors=True)
