# -*- coding: utf-8 -*-
"""Tests for pipeline/align.py — whisper fallback alignment.

faster_whisper is always faked via sys.modules; no model is ever loaded
and no network is touched.
"""

from __future__ import annotations

import types
from types import SimpleNamespace

import pytest

from pipeline import align, contract
from pipeline.contract import Project
from pipeline.errors import StageError

CFG = {"transcribe": {"model": "small", "device": "cpu", "compute_type": "int8"}}

SCRIPT = {
    "meta": {
        "source_url": "https://example.com/v",
        "audience": "general Arab",
        "dialect": "MSA",
        "target_seconds": 90,
    },
    "hook": "خطاف تجريبي",
    "scenes": [
        {
            "id": 1,
            "narration_ar": "مرحبا بكم في عالم التقنية",
            "keywords": [["technology abstract loop"]],
            "mood": "calm",
            "target_seconds": 8,
        },
        {
            "id": 2,
            "narration_ar": "هذا اختبار بسيط",
            "keywords": [["desk simple test"]],
            "mood": "energetic",
            "target_seconds": 5,
        },
    ],
    "post": {"title": "", "description": "", "hashtags": []},
}

# Whisper output mirroring the script exactly, with realistic noise:
# leading spaces, tashkeel on the first word, trailing punctuation.
WHISPER_EXACT = [
    (" مرحباً", 0.00, 0.40),
    (" بكم", 0.40, 0.75),
    (" في", 0.75, 0.95),
    (" عالم", 0.95, 1.40),
    (" التقنية.", 1.40, 2.00),
    (" هذا", 3.00, 3.30),
    (" اختبار", 3.30, 3.90),
    (" بسيط", 3.90, 4.40),
]
DURATION = 5.0


def install_fake_whisper(monkeypatch, words, duration=DURATION):
    """Replace the faster_whisper module with a canned-output fake."""
    segment = SimpleNamespace(
        words=[SimpleNamespace(word=w, start=s, end=e) for w, s, e in words]
    )
    info = SimpleNamespace(duration=duration)

    class FakeWhisperModel:
        init_args: tuple = ()
        transcribe_kwargs: dict = {}

        def __init__(self, *args, **kwargs):
            FakeWhisperModel.init_args = (args, kwargs)

        def transcribe(self, path, **kwargs):
            FakeWhisperModel.transcribe_kwargs = kwargs
            segments = [segment] if words else []
            return iter(segments), info

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", mod)
    return FakeWhisperModel


def install_exploding_whisper(monkeypatch):
    """A fake that fails the test if align tries to transcribe at all."""

    class BoomModel:
        def __init__(self, *a, **k):
            raise AssertionError("whisper must not be invoked")

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = BoomModel
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", mod)


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "2026-06-12-test"
    d.mkdir()
    p = Project(dir=d)
    p.write_json(contract.SCRIPT, SCRIPT)
    p.path(contract.VOICEOVER).write_bytes(b"\x00 fake mp3 bytes")
    return p


def scene_by_id(timing, sid):
    return next(s for s in timing["scenes"] if s["id"] == sid)


# --------------------------------------------------------------------------
# Happy path: exact match
# --------------------------------------------------------------------------

def test_exact_match_uses_whisper_times(project, monkeypatch):
    install_fake_whisper(monkeypatch, WHISPER_EXACT)
    align.run(project, CFG, {})

    timing = project.timing()  # validates the contract shape
    assert timing["total_seconds"] == DURATION

    s1 = scene_by_id(timing, 1)
    assert [w["word"] for w in s1["words"]] == SCRIPT["scenes"][0][
        "narration_ar"
    ].split()  # display text preserved, not whisper's noisy text
    assert s1["words"][0]["start"] == 0.0
    assert s1["words"][0]["end"] == 0.40
    assert s1["words"][4]["start"] == 1.40
    assert s1["words"][4]["end"] == 2.00
    assert s1["start"] == 0.0
    assert s1["end"] == pytest.approx(2.15)  # last word end + 0.15 padding

    s2 = scene_by_id(timing, 2)
    assert s2["start"] == 3.0
    assert s2["end"] == pytest.approx(4.55)
    assert s2["words"][2]["end"] == 4.40


def test_exact_match_passes_verify(project, monkeypatch):
    install_fake_whisper(monkeypatch, WHISPER_EXACT)
    align.run(project, CFG, {})
    assert align.verify_timing(project) == []


def test_transcribe_called_with_word_timestamps(project, monkeypatch):
    fake = install_fake_whisper(monkeypatch, WHISPER_EXACT)
    align.run(project, CFG, {})
    assert fake.transcribe_kwargs.get("word_timestamps") is True
    assert fake.init_args[0][0] == "small"


# --------------------------------------------------------------------------
# Missing whisper words -> interpolation
# --------------------------------------------------------------------------

def test_missing_word_is_interpolated(project, monkeypatch):
    missing = [w for w in WHISPER_EXACT if w[0] != " في"]
    install_fake_whisper(monkeypatch, missing)
    align.run(project, CFG, {})

    timing = project.timing()
    s1 = scene_by_id(timing, 1)
    fi = s1["words"][2]  # "في" was never recognized
    assert fi["start"] == pytest.approx(0.75)  # previous matched word's end
    assert fi["end"] == pytest.approx(0.95)    # next matched word's start
    # neighbors keep their real whisper times
    assert s1["words"][1]["end"] == 0.75
    assert s1["words"][3]["start"] == 0.95


def test_multiple_missing_words_split_the_gap(project, monkeypatch):
    # drop "بكم" and "في": two unmatched words share [0.40, 0.95]
    missing = [w for w in WHISPER_EXACT if w[0] not in (" بكم", " في")]
    install_fake_whisper(monkeypatch, missing)
    align.run(project, CFG, {})

    s1 = scene_by_id(project.timing(), 1)
    w1, w2 = s1["words"][1], s1["words"][2]
    assert w1["start"] == pytest.approx(0.40)
    assert w1["end"] == pytest.approx(w2["start"])
    assert w2["end"] == pytest.approx(0.95)
    # monotonic, equal slices
    assert w1["end"] - w1["start"] == pytest.approx(w2["end"] - w2["start"], abs=2e-3)


def test_missing_tail_interpolates_to_total(project, monkeypatch):
    missing = WHISPER_EXACT[:-1]  # whisper never heard the final word
    install_fake_whisper(monkeypatch, missing)
    align.run(project, CFG, {})

    s2 = scene_by_id(project.timing(), 2)
    last = s2["words"][-1]
    assert last["start"] == pytest.approx(3.90)
    assert last["end"] == pytest.approx(DURATION)


# --------------------------------------------------------------------------
# Extra whisper words are ignored
# --------------------------------------------------------------------------

def test_extra_whisper_words_ignored(project, monkeypatch):
    noisy = list(WHISPER_EXACT)
    noisy[4] = (" التقنية.", 1.55, 2.00)
    noisy.insert(4, (" يعني", 1.40, 1.55))  # filler word not in the script
    install_fake_whisper(monkeypatch, noisy)
    align.run(project, CFG, {})

    timing = project.timing()
    s1 = scene_by_id(timing, 1)
    assert len(s1["words"]) == 5  # filler did not leak into the timeline
    assert s1["words"][4]["start"] == 1.55
    assert s1["words"][3]["end"] == 1.40


# --------------------------------------------------------------------------
# Idempotency / force / repair
# --------------------------------------------------------------------------

VALID_SENTINEL_TIMING = {
    "total_seconds": 9.0,
    "scenes": [
        {
            "id": 1,
            "start": 0.0,
            "end": 9.0,
            "words": [{"word": "كلمة", "start": 0.0, "end": 1.0}],
        }
    ],
}


def test_existing_valid_timing_returns_early(project, monkeypatch):
    project.write_json(contract.TIMING, VALID_SENTINEL_TIMING)
    install_exploding_whisper(monkeypatch)
    align.run(project, CFG, {})  # must not touch whisper
    assert project.timing()["total_seconds"] == 9.0


def test_force_rebuilds_over_valid_timing(project, monkeypatch):
    project.write_json(contract.TIMING, VALID_SENTINEL_TIMING)
    install_fake_whisper(monkeypatch, WHISPER_EXACT)
    align.run(project, CFG, {}, force=True)
    timing = project.timing()
    assert timing["total_seconds"] == DURATION
    assert len(timing["scenes"]) == 2


def test_garbled_timing_is_rebuilt_without_force(project, monkeypatch):
    project.write_json(contract.TIMING, {"total_seconds": "garbled"})
    install_fake_whisper(monkeypatch, WHISPER_EXACT)
    align.run(project, CFG, {})
    timing = project.timing()
    assert timing["total_seconds"] == DURATION
    assert len(timing["scenes"]) == 2


# --------------------------------------------------------------------------
# Failure modes
# --------------------------------------------------------------------------

def test_missing_voiceover_raises_contract_error(project, monkeypatch):
    # Missing contracted input -> ContractError (consistent across stages).
    project.path(contract.VOICEOVER).unlink()
    install_fake_whisper(monkeypatch, WHISPER_EXACT)
    with pytest.raises(contract.ContractError) as exc:
        align.run(project, CFG, {})
    assert contract.VOICEOVER in str(exc.value)


def test_no_recognized_words_raises_stage_error(project, monkeypatch):
    install_fake_whisper(monkeypatch, [], duration=1.0)
    with pytest.raises(StageError):
        align.run(project, CFG, {})


# --------------------------------------------------------------------------
# verify_timing
# --------------------------------------------------------------------------

def test_verify_timing_reports_problems(project):
    project.write_json(
        contract.TIMING,
        {
            "total_seconds": 10.0,
            "scenes": [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.0,
                    "words": [
                        {"word": "أول", "start": 0.0, "end": 0.5},
                        {"word": "ثاني", "start": 1.0, "end": 0.8},  # ends early
                        {"word": "ثالث", "start": 0.2, "end": 0.6},  # rewinds
                        {"word": "رابع", "start": 1.5, "end": 2.5},  # out of bounds
                    ],
                },
                {
                    "id": 2,
                    "start": 3.5,  # 1.5s gap after scene 1
                    "end": 5.0,
                    "words": [{"word": "خامس", "start": 3.5, "end": 5.0}],
                },
            ],
        },
    )
    warnings = align.verify_timing(project)
    assert len(warnings) == 4
    joined = "\n".join(warnings)
    assert "ends before it starts" in joined
    assert "non-monotonic" in joined
    assert "outside scene bounds" in joined
    assert "between scenes" in joined


def test_verify_timing_clean(project):
    project.write_json(
        contract.TIMING,
        {
            "total_seconds": 4.0,
            "scenes": [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.0,
                    "words": [
                        {"word": "أول", "start": 0.0, "end": 0.9},
                        {"word": "ثاني", "start": 0.9, "end": 1.9},
                    ],
                },
                {
                    "id": 2,
                    "start": 2.4,
                    "end": 4.0,
                    "words": [{"word": "ثالث", "start": 2.4, "end": 3.9}],
                },
            ],
        },
    )
    assert align.verify_timing(project) == []
