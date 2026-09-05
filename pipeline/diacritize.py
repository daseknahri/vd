"""Arabic diacritization (auto-tashkeel) for TTS pronunciation.

Undiacritized MSA forces a TTS to guess short vowels, so many correctly-spelled
words come out mispronounced. CATT (abjadai, Apache-2.0, ONNX/CPU — no torch)
adds harakat to the text before synthesis. This is the systemic fix that
`pronunciation.json` only patched word by word.

Contract kept by the voice stage:
- Applied to the SPOKEN copy only; display/caption text stays the plain spelling.
- Word count is preserved (CATT adds marks within tokens, never splits them), so
  the caption/timing 1:1 word map is untouched. If a result's word count ever
  differs, that scene falls back to its plain text (None here) — never a desync.
- Best-effort: if CATT is not installed / fails to load, every result is None and
  the caller uses plain text. Diacritization must never crash the pipeline.

CATT prints an emoji banner on first-run model download; the Windows console
codepage (cp1252) can't encode it, so all CATT calls run with stdout/stderr
redirected to an in-memory sink (also keeps its progress chatter out of logs).
"""

from __future__ import annotations

import contextlib
import io
from typing import Any

_MODEL: Any = None
_TRIED = False


def _load() -> Any:
    """Load the CATT model once (≈7s), cached. Returns None if unavailable."""
    global _MODEL, _TRIED
    if _MODEL is not None:
        return _MODEL
    if _TRIED:
        return None
    _TRIED = True
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            from catt_tashkeel import CATTEncoderOnly
            _MODEL = CATTEncoderOnly()
    except Exception:  # noqa: BLE001 — any failure => diacritization is off
        _MODEL = None
    return _MODEL


def available() -> bool:
    return _load() is not None


def diacritize_batch(texts: list[str]) -> list[str | None]:
    """Diacritize each text. Result[i] is the fully-diacritized string, or None
    when diacritization is unavailable or would change the word count (so the
    caller keeps that scene's plain text). Never raises."""
    if not texts:
        return []
    model = _load()
    if model is None:
        return [None] * len(texts)
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            out = model.do_tashkeel_batch([t.strip() for t in texts], verbose=False)
    except Exception:  # noqa: BLE001 — degrade to plain text, never crash voice
        return [None] * len(texts)
    result: list[str | None] = []
    for src, dia in zip(texts, out):
        if isinstance(dia, str) and len(dia.split()) == len(src.strip().split()):
            result.append(dia)
        else:
            result.append(None)  # word-count drift -> fall back for this scene
    return result


def reset_cache() -> None:
    """Test hook: force the model to reload on the next call."""
    global _MODEL, _TRIED
    _MODEL = None
    _TRIED = False
