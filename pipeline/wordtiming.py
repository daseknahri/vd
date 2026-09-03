"""Pure word-timing helpers shared by the align stage and the TTS worker.

Dependency-free (stdlib only: difflib, unicodedata) so it is importable both in
the pipeline venv and in the separate GPU worker venv (scripts/tts_worker.py).
Single source of truth for the tricky Arabic-aware word matching + gap
interpolation; `pipeline/align.py` and the worker both build on it.
"""

from __future__ import annotations

import difflib
import unicodedata

# Arabic tashkeel/diacritics U+064B..U+0652 — recognized text and script text
# disagree on these constantly, so matching ignores them.
_TASHKEEL = frozenset(chr(c) for c in range(0x064B, 0x0653))
_TATWEEL = "ـ"


def normalize(word: str) -> str:
    """Matching form: no tashkeel, no tatweel, no punctuation, no spaces."""
    kept = []
    for ch in unicodedata.normalize("NFC", word):
        if ch in _TASHKEEL or ch == _TATWEEL or ch.isspace():
            continue
        if unicodedata.category(ch).startswith("P"):
            continue
        kept.append(ch)
    return "".join(kept).casefold()


def match_times(
    ref_words: list[str],
    ref_times: list[tuple[float, float] | None],
    target_words: list[str],
) -> list[tuple[float, float] | None]:
    """For each target word, the (start, end) of the ref word it aligns to via
    difflib on normalized forms; None where unmatched. `ref_times[i]` pairs with
    `ref_words[i]`. Words that normalize to "" (pure punctuation) get a per-side
    unique sentinel so two empties never spuriously match."""
    a = [normalize(w) or f"a{i}" for i, w in enumerate(ref_words)]
    b = [normalize(w) or f"b{i}" for i, w in enumerate(target_words)]
    out: list[tuple[float, float] | None] = [None] * len(target_words)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            t = ref_times[block.a + k]
            if t is not None:
                out[block.b + k] = t
    return out


def fill_gaps(
    times: list[tuple[float, float] | None], total: float
) -> list[tuple[float, float]]:
    """Linear interpolation for unmatched words between matched neighbors.
    With nothing matched, distribute the whole span evenly."""
    n = len(times)
    matched = [i for i, t in enumerate(times) if t is not None]
    if not matched:
        step = total / n if n else 0.0
        return [(i * step, (i + 1) * step) for i in range(n)]

    out: list = list(times)

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


def char_alignment(
    spoken_words: list[str], word_times: list[tuple[float, float]]
) -> dict:
    """Expand per-word [start, end] into ElevenLabs' character-level alignment
    shape (characters + per-character start/end arrays, space between words).
    voice.py's `_words_from_alignment` regroups this by whitespace and recovers
    exactly each word's [start, end] — so an open TTS + forced-alignment path is
    a drop-in for the ElevenLabs alignment the caption stage consumes."""
    chars: list[str] = []
    starts: list[float] = []
    ends: list[float] = []
    for i, word in enumerate(spoken_words):
        ws, we = word_times[i]
        we = max(we, ws)
        n = max(len(word), 1)
        for j, ch in enumerate(word):
            chars.append(ch)
            starts.append(ws + (we - ws) * j / n)
            ends.append(ws + (we - ws) * (j + 1) / n)
        if i < len(spoken_words) - 1:  # word separator (whitespace = boundary)
            chars.append(" ")
            starts.append(we)
            ends.append(we)
    return {
        "characters": chars,
        "character_start_times_seconds": starts,
        "character_end_times_seconds": ends,
    }
