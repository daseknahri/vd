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

import difflib
import unicodedata
from pathlib import Path
from typing import Any

from pipeline import contract
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

STAGE = "align"
SCENE_END_PADDING = 0.15  # seconds added after a scene's last word

# Arabic tashkeel/diacritics U+064B..U+0652 — whisper output and script text
# disagree on these constantly, so matching ignores them.
_TASHKEEL = frozenset(chr(c) for c in range(0x064B, 0x0653))
_TATWEEL = "ـ"


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

def _normalize(word: str) -> str:
    """Matching form: no tashkeel, no tatweel, no punctuation, no spaces."""
    kept = []
    for ch in unicodedata.normalize("NFC", word):
        if ch in _TASHKEEL or ch == _TATWEEL or ch.isspace():
            continue
        if unicodedata.category(ch).startswith("P"):
            continue
        kept.append(ch)
    return "".join(kept).casefold()


def _norm_seq(tokens: list[str], side: str) -> list[str]:
    # Words that normalize to "" (pure punctuation) get a per-side unique
    # sentinel so two empties never count as a match. The U+E000 private-use
    # prefix guarantees a sentinel can never equal a real normalized word.
    return [
        _normalize(t) or f"{side}{i}" for i, t in enumerate(tokens)
    ]


def _match_times(
    whisper_words: list[dict[str, Any]], display_tokens: list[str]
) -> list[tuple[float, float] | None]:
    """Whisper times for each display token; None where unmatched."""
    a = _norm_seq([w["word"] for w in whisper_words], "w")
    b = _norm_seq(display_tokens, "d")
    times: list[tuple[float, float] | None] = [None] * len(display_tokens)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            w = whisper_words[block.a + k]
            times[block.b + k] = (w["start"], w["end"])
    return times


def _fill_gaps(
    times: list[tuple[float, float] | None], total: float
) -> list[tuple[float, float]]:
    """Linear interpolation for unmatched words between matched neighbors."""
    n = len(times)
    matched = [i for i, t in enumerate(times) if t is not None]
    if not matched:
        step = total / n if n else 0.0
        return [(i * step, (i + 1) * step) for i in range(n)]

    out: list[Any] = list(times)

    def fill(lo: int, hi: int, left: float, right: float) -> None:
        count = hi - lo + 1
        right = max(right, left)
        step = (right - left) / count
        for g in range(count):
            out[lo + g] = (left + g * step, left + (g + 1) * step)

    first, last = matched[0], matched[-1]
    if first > 0:
        fill(0, first - 1, 0.0, out[first][0])
    for left_i, right_i in zip(matched, matched[1:]):
        if right_i - left_i > 1:
            fill(left_i + 1, right_i - 1, out[left_i][1], out[right_i][0])
    if last < n - 1:
        fill(last + 1, n - 1, out[last][1], total)
    return out


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
