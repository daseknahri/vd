"""Preflight checks: is this checkout ready to make videos?

`run.py doctor` runs these and prints a grouped checklist. Two severities
of requirement, because "ready" means different things at different times:

- **toolchain** — the local machine can render at all (ffmpeg, Pillow's
  raqm Arabic shaping, the caption font, a parseable config). A failure
  here breaks every project regardless of API keys, so it FAILS the check
  (exit 1).
- **go-live** — needed only once you actually spend money / hit the network
  (ElevenLabs key + voice id, a footage key, a music bed). Before you have
  filled `.env` these are legitimately absent, so they WARN, never fail —
  the point is to list exactly what is left to configure.

This module does no I/O beyond reading config/fonts/music that already
exist; it never calls a paid API. Heavy, stage-only dependencies
(yt-dlp, faster-whisper) are probed by import-spec presence, not imported.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from pipeline import contract
from pipeline.contract import ContractError

OK = "ok"
WARN = "warn"
FAIL = "fail"

MUSIC_EXTS = {".mp3", ".m4a", ".wav"}


@dataclass
class Check:
    """One preflight line. `required` checks fail the overall result."""

    name: str
    status: str          # OK | WARN | FAIL
    detail: str
    required: bool       # True = toolchain; False = go-live


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------

def _check_ffmpeg(tool: str) -> Check:
    try:
        path = contract.ffmpeg_path(tool)
        return Check(tool, OK, path, required=True)
    except FileNotFoundError as exc:
        return Check(tool, FAIL, str(exc), required=True)


def _check_raqm() -> Check:
    # Import here so a broken Pillow surfaces as a FAIL line, not an
    # import-time crash of the whole doctor command.
    try:
        from PIL import features
    except Exception as exc:  # pragma: no cover - Pillow missing entirely
        return Check("pillow raqm", FAIL, f"Pillow not importable: {exc}",
                     required=True)
    if features.check("raqm"):
        return Check("pillow raqm", OK, "Arabic shaping available",
                     required=True)
    return Check(
        "pillow raqm", FAIL,
        "Pillow built without libraqm - Arabic captions would render "
        "unshaped; reinstall pillow with raqm support",
        required=True,
    )


def _check_caption_font(cfg: dict | None) -> Check:
    font_name = str(((cfg or {}).get("captions") or {}).get("font") or "").strip()
    if not font_name:
        return Check("caption font", FAIL,
                     "captions.font is not set in config", required=True)
    try:
        from pipeline.captions import FONTS_DIR, _font_file
        path = _font_file(FONTS_DIR, font_name)
    except ContractError as exc:
        return Check("caption font", FAIL, str(exc), required=True)
    except Exception as exc:  # pragma: no cover - defensive
        return Check("caption font", FAIL,
                     f"font resolution failed: {exc}", required=True)
    return Check("caption font", OK, f"{font_name} -> {path.name}",
                 required=True)


def _check_dependencies() -> list[Check]:
    """Import-spec presence for the libraries stages need. Split by when
    they matter: the render/caption path is toolchain; ingest's heavy
    models are go-live (only the ingest stage needs them)."""
    toolchain = {
        "requests": "HTTP (voice/footage)",
        "yaml": "config parsing",
        "dotenv": "reading .env",
        "PIL": "caption rendering",
        "fontTools": "font resolution",
    }
    golive = {
        "yt_dlp": "ingest download (URL-first) + dub source download",
        "faster_whisper": "ingest transcription (URL-first) + dub segmentation",
    }
    checks: list[Check] = []
    for mod, why in toolchain.items():
        present = importlib.util.find_spec(mod) is not None
        checks.append(Check(
            f"dep {mod}", OK if present else FAIL,
            why if present else f"missing - required for {why}",
            required=True,
        ))
    for mod, why in golive.items():
        present = importlib.util.find_spec(mod) is not None
        checks.append(Check(
            f"dep {mod}", OK if present else WARN,
            why if present else f"missing - required for {why}",
            required=False,
        ))
    return checks


def _check_env_key(env: dict, key: str, why: str) -> Check:
    if env.get(key):
        return Check(key, OK, "set", required=False)
    return Check(key, WARN, f"not set - required for {why}", required=False)


def _check_voice_id(cfg: dict | None) -> Check:
    voice_id = str(((cfg or {}).get("voice") or {}).get("voice_id") or "").strip()
    if voice_id:
        return Check("voice.voice_id", OK, "set", required=False)
    return Check("voice.voice_id", WARN,
                 "empty - set your ElevenLabs voice id in config.yaml",
                 required=False)


def _check_footage_keys(env: dict) -> Check:
    have = [k for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY") if env.get(k)]
    if have:
        return Check("footage key", OK, ", ".join(have), required=False)
    return Check("footage key", WARN,
                 "no PEXELS_API_KEY or PIXABAY_API_KEY - required for the "
                 "footage stage", required=False)


def _check_music(cfg: dict | None) -> Check:
    music_dir = ((cfg or {}).get("audio") or {}).get("music_dir")
    if not music_dir:
        return Check("music bed", WARN,
                     "audio.music_dir not set - videos render voice-only",
                     required=False)
    d = Path(music_dir)
    if not d.is_absolute():
        d = contract.ROOT / d
    beds = ([p for p in d.iterdir()
             if p.is_file() and p.suffix.lower() in MUSIC_EXTS]
            if d.is_dir() else [])
    if beds:
        return Check("music bed", OK,
                     f"{len(beds)} in {music_dir}", required=False)
    return Check("music bed", WARN,
                 f"none in {music_dir} - videos render voice-only "
                 "(drop a royalty-free bed there)", required=False)


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------

def run_checks(cfg: dict | None, env: dict,
               config_error: str | None = None) -> list[Check]:
    """All preflight checks, toolchain first then go-live."""
    checks: list[Check] = [
        _check_ffmpeg("ffmpeg"),
        _check_ffmpeg("ffprobe"),
        _check_raqm(),
    ]
    checks.extend(_check_dependencies())
    if config_error is not None:
        checks.append(Check("config.yaml", FAIL, config_error, required=True))
    else:
        checks.append(Check("config.yaml", OK, "parsed", required=True))
    checks.append(_check_caption_font(cfg))
    # go-live
    checks.append(_check_env_key(env, "ELEVENLABS_API_KEY",
                                 "the voice stage (TTS)"))
    checks.append(_check_voice_id(cfg))
    checks.append(_check_footage_keys(env))
    checks.append(_check_music(cfg))
    return checks


def has_failures(checks: list[Check]) -> bool:
    return any(c.status == FAIL for c in checks)
