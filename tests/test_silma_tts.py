# -*- coding: utf-8 -*-
"""SILMA provider tests. The worker + whisper are mocked — no SILMA venv, no
model, no network. Verifies the provider contract (mp3 + alignment shape) and the
alignment word-count preservation."""

import base64
import io
import wave

import pytest

from pipeline import silma_tts
from pipeline.contract import ContractError
from pipeline.errors import StageError


def _tiny_wav(seconds=0.5, sr=24000):
    n = int(seconds * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


class _Word:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


class _Seg:
    def __init__(self, words):
        self.words = words


class FakeWhisper:
    def __init__(self, words):
        self._words = words

    def transcribe(self, path, word_timestamps=True, language=None):
        return [_Seg(self._words)], None


def test_build_uses_bundled_reference_by_default():
    p = silma_tts.build({}, {})
    assert p.ref_file == str(silma_tts.DEFAULT_REF_FILE)
    assert p.force_tashkeel is True and p.nfe_step == 16


def test_signature_changes_with_seed():
    a = silma_tts.build({"silma": {"seed": 1}}, {})
    b = silma_tts.build({"silma": {"seed": 2}}, {})
    assert a.signature() != b.signature()


def test_align_preserves_word_count(monkeypatch):
    p = silma_tts.build({}, {})
    heard = [_Word("مرحبا", 0.0, 0.3), _Word("بكم", 0.3, 0.6)]
    monkeypatch.setattr(p, "_whisper", lambda: FakeWhisper(heard))
    align = p._align(_tiny_wav(), 24000, "مرحبا بكم")
    # regrouping the characters by whitespace must recover the 2 display words
    assert "".join(align["characters"]).split() == ["مرحبا", "بكم"]
    assert len(align["characters"]) == len(align["character_start_times_seconds"])
    assert len(align["characters"]) == len(align["character_end_times_seconds"])


def test_synthesize_returns_mp3_and_alignment(monkeypatch):
    p = silma_tts.build({}, {})
    monkeypatch.setattr(p, "_request", lambda payload: {
        "ok": True, "wav_b64": base64.b64encode(_tiny_wav()).decode(), "sr": 24000})
    monkeypatch.setattr(silma_tts, "_wav_to_mp3", lambda wav: b"MP3BYTES")
    monkeypatch.setattr(p, "_align", lambda wav, sr, text: {"characters": list(text)})
    audio, align = p.synthesize("مرحبا بكم", "", "")
    assert audio == b"MP3BYTES" and align["characters"] == list("مرحبا بكم")


def test_synthesize_raises_on_worker_error(monkeypatch):
    p = silma_tts.build({}, {})
    monkeypatch.setattr(p, "_request", lambda payload: {"ok": False, "error": "boom"})
    with pytest.raises(StageError, match="boom"):
        p.synthesize("x", "", "")


def test_request_payload_carries_ref_and_text(monkeypatch):
    p = silma_tts.build({"silma": {"ref_file": "r.wav", "ref_text": "ref"}}, {})
    seen = {}
    monkeypatch.setattr(p, "_request", lambda payload: seen.update(payload) or {
        "ok": True, "wav_b64": base64.b64encode(_tiny_wav()).decode(), "sr": 24000})
    monkeypatch.setattr(silma_tts, "_wav_to_mp3", lambda wav: b"m")
    monkeypatch.setattr(p, "_align", lambda *a: {"characters": []})
    p.synthesize("النص", "prev", "next")
    assert seen["text"] == "النص"
    assert seen["ref_file"].replace("\\", "/").endswith("r.wav")  # resolved abs path
    assert seen["ref_text"] == "ref" and seen["force_tashkeel"] is True


def test_resolve_reference_default_is_bundled():
    rf, rt = silma_tts._resolve_reference({})
    assert rf == str(silma_tts.DEFAULT_REF_FILE) and rt == silma_tts.DEFAULT_REF_TEXT


def test_resolve_reference_reads_sibling_transcript(tmp_path):
    wav = tmp_path / "narr.wav"
    wav.write_bytes(b"\0")
    (tmp_path / "narr.txt").write_text("نص المرجع", encoding="utf-8")
    rf, rt = silma_tts._resolve_reference({"ref_file": str(wav)})
    assert rf == str(wav) and rt == "نص المرجع"


def test_resolve_reference_inline_text_wins(tmp_path):
    wav = tmp_path / "narr.wav"
    wav.write_bytes(b"\0")
    _rf, rt = silma_tts._resolve_reference(
        {"ref_file": str(wav), "ref_text": "inline"})
    assert rt == "inline"


def test_resolve_reference_missing_transcript_raises(tmp_path):
    wav = tmp_path / "narr.wav"
    wav.write_bytes(b"\0")
    with pytest.raises(ContractError, match="ref_text"):
        silma_tts._resolve_reference({"ref_file": str(wav)})
