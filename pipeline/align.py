"""Fallback word-level alignment (align stage).

When ElevenLabs timestamps are missing or garbled, rebuild timing.json by
transcribing voiceover.mp3 locally with faster-whisper (word_timestamps=True)
and aligning the recognized words to the script's display words.

Alignment: the global whisper word sequence is matched against the global
display word sequence (scene order) with difflib.SequenceMatcher on
normalized forms. Matched display words inherit whisper times; unmatched
ones get times linearly interpolated between their nearest matched
neighbors. Scene boundaries derive from their first/last word.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline import contract, wordtiming
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

STAGE = "align"
SCENE_END_PADDING = 0.15  # seconds added after a scene's last word


def run(project: Project, cfg: dict, env: dict, *, force: bool = False) -> None:
    """Build timing.json from a local whisper transcription of the voiceover."""
    if not force and project.has(contract.TIMING):
        try:
            project.timing()
            return
        except ContractError:
            pass  # garbled timing.json is exactly what this fallback repairs

    script = project.script()
    audio = project.path(contract.VOICEOVER)
    if not audio.exists():
        # Missing contracted input = contract violation (consistent with
        # ingest/render).
        raise ContractError(
            f"{contract.VOICEOVER} not found in {project.dir} — "
            f"run the voice stage first"
        )

    whisper_words, total = _transcribe(audio, cfg)
    if not whisper_words:
        raise StageError(STAGE, "faster-whisper recognized no words in the voiceover")

    timing = _build_timing(script, whisper_words, total)
    contract.validate_timing(timing)
    project.write_json(contract.TIMING, timing)


def verify_timing(project: Project) -> list[str]:
    """Sanity warnings for the orchestrator. Empty list = looks healthy."""
    timing = project.timing()
    warnings: list[str] = []
    tol = 1e-3

    for scene in timing["scenes"]:
        sid = scene["id"]
        prev_start: float | None = None
        for idx, w in enumerate(scene["words"]):
            if w["end"] < w["start"] - tol:
                warnings.append(
                    f"scene {sid}: word {idx} ({w['word']!r}) ends before it "
                    f"starts ({w['end']:.2f} < {w['start']:.2f})"
                )
            if prev_start is not None and w["start"] < prev_start - tol:
                warnings.append(
                    f"scene {sid}: word {idx} ({w['word']!r}) is non-monotonic "
                    f"— starts at {w['start']:.2f}, before previous word at "
                    f"{prev_start:.2f}"
                )
            if w["start"] < scene["start"] - tol or w["end"] > scene["end"] + tol:
                warnings.append(
                    f"scene {sid}: word {idx} ({w['word']!r}) at "
                    f"{w['start']:.2f}-{w['end']:.2f} lies outside scene "
                    f"bounds {scene['start']:.2f}-{scene['end']:.2f}"
                )
            prev_start = w["start"]

    ordered = sorted(timing["scenes"], key=lambda s: s["start"])
    for a, b in zip(ordered, ordered[1:]):
        gap = b["start"] - a["end"]
        if gap > 1.0:
            warnings.append(
                f"scene {a['id']} -> scene {b['id']}: {gap:.2f}s of silence "
                f"between scenes"
            )
    return warnings


# --------------------------------------------------------------------------
# Whisper transcription
# --------------------------------------------------------------------------

def _transcribe(audio: Path, cfg: dict) -> tuple[list[dict[str, Any]], float]:
    """Return ([{word, start, end}...], total_seconds) for the voiceover."""
    tcfg = cfg.get("transcribe") or {}
    # Lazy: importing faster_whisper loads heavy native deps.
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(
            tcfg.get("model", "small"),
            device=tcfg.get("device", "cpu"),
            compute_type=tcfg.get("compute_type", "int8"),
        )
        segments, info = model.transcribe(
            str(audio), word_timestamps=True, language="ar"
        )
        words: list[dict[str, Any]] = []
        for segment in segments:
            for w in segment.words or []:
                words.append(
                    {"word": w.word, "start": float(w.start), "end": float(w.end)}
                )
    except Exception as exc:
        raise StageError(STAGE, f"faster-whisper transcription failed: {exc}") from exc

    total = getattr(info, "duration", None)
    if not isinstance(total, (int, float)) or total <= 0:
        total = words[-1]["end"] if words else 0.0
    if words:
        total = max(float(total), words[-1]["end"])
    return words, float(total)


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------
# Word matching + gap interpolation now live in pipeline/wordtiming.py (shared
# with the TTS worker); thin wrappers keep _build_timing's call sites unchanged.

def _match_times(
    whisper_words: list[dict[str, Any]], display_tokens: list[str]
) -> list[tuple[float, float] | None]:
    """Whisper times for each display token; None where unmatched."""
    return wordtiming.match_times(
        [w["word"] for w in whisper_words],
        [(w["start"], w["end"]) for w in whisper_words],
        display_tokens,
    )


_fill_gaps = wordtiming.fill_gaps


def _build_timing(
    script: dict[str, Any], whisper_words: list[dict[str, Any]], total: float
) -> dict[str, Any]:
    display_tokens: list[str] = []
    per_scene_tokens: list[tuple[int, list[str]]] = []
    for scene in script["scenes"]:
        tokens = scene["narration_ar"].split()
        per_scene_tokens.append((scene["id"], tokens))
        display_tokens.extend(tokens)

    filled = _fill_gaps(_match_times(whisper_words, display_tokens), total)

    scenes_out = []
    pos = 0
    for scene_id, tokens in per_scene_tokens:
        words = []
        for token in tokens:
            start, end = filled[pos]
            pos += 1
            words.append(
                {"word": token, "start": round(start, 3), "end": round(end, 3)}
            )
        s_start = words[0]["start"]
        s_end = min(words[-1]["end"] + SCENE_END_PADDING, total)
        if s_end <= s_start:  # degenerate zero-length scene at the tail
            s_end = s_start + 0.01
        scenes_out.append(
            {
                "id": scene_id,
                "start": s_start,
                "end": round(s_end, 3),
                "words": words,
            }
        )

    return {"total_seconds": round(total, 3), "scenes": scenes_out}
