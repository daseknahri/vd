# -*- coding: utf-8 -*-
"""Chatterbox provider: voice.py routing + provider contract.

The GPU worker subprocess is mocked — no torch, no models, no downloads. These
verify the wiring (provider selection, cache signature, response handling), not
the ML quality (that's validated live)."""

import pytest

from pipeline import chatterbox_tts, voice
from pipeline.contract import ContractError
from pipeline.errors import StageError

CBX_CFG = {"voice": {"provider": "chatterbox",
                     "chatterbox": {"ai_python": "x", "language": "ar", "seed": 7}}}


# -- voice._build_provider routing ---------------------------------------------
def test_build_provider_routes_to_chatterbox():
    prov = voice._build_provider(CBX_CFG, {})
    assert isinstance(prov, chatterbox_tts.ChatterboxTTS)
    assert prov.language == "ar"


def test_build_provider_chatterbox_needs_no_key_or_voice_id():
    # No ELEVENLABS_API_KEY and no voice_id present — must NOT raise.
    voice._build_provider(CBX_CFG, {})


def test_build_provider_unknown_provider_raises():
    with pytest.raises(ContractError, match="not implemented"):
        voice._build_provider({"voice": {"provider": "nope"}}, {})


def test_build_provider_elevenlabs_still_requires_voice_id():
    with pytest.raises(ContractError, match="voice_id"):
        voice._build_provider({"voice": {"provider": "elevenlabs", "voice_id": ""}}, {})


# -- signature (cache key) -----------------------------------------------------
def _prov(**over):
    cfg = {"ai_python": "x", "language": "ar", "voice_ref": "", "seed": 1}
    cfg.update(over)
    return chatterbox_tts.build({"chatterbox": cfg}, {})


def test_signature_is_stable():
    assert _prov().signature() == _prov().signature()


def test_signature_changes_with_settings():
    base = _prov().signature()
    assert _prov(seed=2).signature() != base
    assert _prov(exaggeration=0.9).signature() != base


# -- synthesize (worker mocked) ------------------------------------------------
def test_synthesize_returns_mp3_and_alignment(monkeypatch):
    prov = _prov()
    align = {"characters": list("مرحبا"),
             "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4],
             "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5]}
    monkeypatch.setattr(prov, "_request",
                        lambda payload: {"ok": True, "wav_b64": "AAAA", "alignment": align})
    monkeypatch.setattr(chatterbox_tts, "_wav_to_mp3", lambda wav: b"MP3")
    audio, out = prov.synthesize("مرحبا", "prev", "next")
    assert audio == b"MP3"
    assert out["characters"] == list("مرحبا")


def test_synthesize_error_response_raises(monkeypatch):
    prov = _prov()
    monkeypatch.setattr(prov, "_request", lambda payload: {"ok": False, "error": "boom"})
    with pytest.raises(StageError, match="boom"):
        prov.synthesize("x", "", "")


def test_synthesize_malformed_alignment_raises(monkeypatch):
    prov = _prov()
    monkeypatch.setattr(prov, "_request",
                        lambda payload: {"ok": True, "wav_b64": "AAAA",
                                         "alignment": {"characters": "notalist"}})
    monkeypatch.setattr(chatterbox_tts, "_wav_to_mp3", lambda wav: b"MP3")
    with pytest.raises(StageError):
        prov.synthesize("x", "", "")
