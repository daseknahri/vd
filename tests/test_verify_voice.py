# -*- coding: utf-8 -*-
"""Voice-content audit tests. Pure analysis is exercised directly; heal/fix are
exercised with a fake provider + fake transcription — no whisper, no GPU, no
network. Arabic lives in these source literals (fine); it never reaches a
console or a command string."""

import copy
import json

import pytest

from pipeline import contract, verify_voice as vv, voice
from pipeline.contract import Project

SCRIPT = {
    "meta": {"source_url": "topic://x", "audience": "general Arab",
             "dialect": "MSA", "target_seconds": 30},
    "hook": "سؤال",
    "scenes": [
        {"id": 1, "narration_ar": "الألف والباء والتاء",
         "keywords": [["a"]], "mood": "calm", "target_seconds": 6},
        {"id": 2, "narration_ar": "حرية اختيار رد فعله تجاهه",
         "keywords": [["b"]], "mood": "energetic", "target_seconds": 6},
    ],
    "post": {"title": "t", "description": "d", "hashtags": ["#x"]},
}


def _make_project(tmp_path, script=SCRIPT):
    d = tmp_path / "2026-09-05-audit"
    d.mkdir()
    project = Project(dir=d)
    project.write_json(contract.SCRIPT, copy.deepcopy(script))
    return project


# -- pure: near-dup + repeat detection --------------------------------------

def test_near_dup_matches_exact_and_truncated_echo():
    assert vv._near_dup("تجاهه", "تجاهه")      # identical
    assert vv._near_dup("تجاهه", "تجاه")        # truncated echo (the real bug)
    assert vv._near_dup("تجاه", "تجاهه")        # order-independent


def test_near_dup_rejects_distinct_and_too_short():
    assert not vv._near_dup("رد", "فعله")       # distinct words
    assert not vv._near_dup("في", "فيه")         # shorter than 3 chars -> not a stutter
    assert not vv._near_dup("", "شيء")           # empty


def test_find_repeats_flags_the_stutter():
    script = "حرية اختيار رد فعله تجاهه".split()
    heard = "حرية اختيار رد فعله تجاهه تجاه".split()   # تجاهه spoken twice
    assert vv.find_repeats(script, heard) == ["تجاهه تجاه"]


def test_find_repeats_clean_scene_is_empty():
    tokens = "حرية اختيار رد فعله تجاهه".split()
    assert vv.find_repeats(tokens, tokens) == []


def test_find_repeats_ignores_a_legitimate_script_repeat():
    # If the script itself repeats a word, hearing it twice is not a defect.
    script = "يوما يوما بعد ذلك".split()
    heard = "يوما يوما بعد ذلك".split()
    assert vv.find_repeats(script, heard) == []


# -- pure: similarity + bucketing + analyze ---------------------------------

def test_scene_similarity_bounds():
    toks = "حرية اختيار رد".split()
    assert vv.scene_similarity(toks, toks) == 1.0
    assert vv.scene_similarity(toks, "قطة كلب سمكة".split()) < 0.4
    assert vv.scene_similarity([], []) == 1.0
    assert vv.scene_similarity(toks, []) == 0.0


def test_bucket_by_scene_places_words_by_midpoint():
    timing = {"scenes": [{"id": 1, "start": 0.0, "end": 2.0},
                         {"id": 2, "start": 2.0, "end": 4.0}]}
    heard = [{"word": "الف", "start": 0.1, "end": 0.5},
             {"word": "باء", "start": 2.2, "end": 2.6}]
    out = vv.bucket_by_scene(timing, heard)
    assert out == {1: ["الف"], 2: ["باء"]}


def test_analyze_flags_repeat_scene_and_low_similarity():
    timing = {"total_seconds": 4.0, "scenes": [
        {"id": 1, "start": 0.0, "end": 2.0},
        {"id": 2, "start": 2.0, "end": 4.0}]}
    # scene 1 heard verbatim; scene 2 stutters on its last word
    heard = [
        {"word": "الألف", "start": 0.2, "end": 0.6},
        {"word": "والباء", "start": 0.7, "end": 1.1},
        {"word": "والتاء", "start": 1.2, "end": 1.6},
        {"word": "حرية", "start": 2.1, "end": 2.4},
        {"word": "اختيار", "start": 2.5, "end": 2.9},
        {"word": "رد", "start": 3.0, "end": 3.2},
        {"word": "فعله", "start": 3.3, "end": 3.5},
        {"word": "تجاهه", "start": 3.6, "end": 3.8},
        {"word": "تجاه", "start": 3.85, "end": 3.99},
    ]
    report = vv.analyze(SCRIPT, timing, heard)
    assert report["repeat_scenes"] == [2]
    assert report["ok"] is False
    scene2 = next(s for s in report["scenes"] if s["id"] == 2)
    assert scene2["repeats"] == ["تجاهه تجاه"]


def test_analyze_clean_run_is_ok():
    timing = {"total_seconds": 4.0, "scenes": [
        {"id": 1, "start": 0.0, "end": 2.0},
        {"id": 2, "start": 2.0, "end": 4.0}]}
    heard = (
        [{"word": w, "start": 0.2 + i * 0.3, "end": 0.4 + i * 0.3}
         for i, w in enumerate(SCRIPT["scenes"][0]["narration_ar"].split())]
        + [{"word": w, "start": 2.2 + i * 0.3, "end": 2.4 + i * 0.3}
           for i, w in enumerate(SCRIPT["scenes"][1]["narration_ar"].split())]
    )
    report = vv.analyze(SCRIPT, timing, heard)
    assert report["ok"] is True
    assert report["repeat_scenes"] == [] and report["low_similarity_scenes"] == []


# -- heal: re-roll loop with a fake provider + fake transcription ------------

def _fake_alignment(text):
    chars = list(text)
    return {
        "characters": chars,
        "character_start_times_seconds": [round(i * 0.1, 4) for i in range(len(chars))],
        "character_end_times_seconds": [round((i + 1) * 0.1, 4) for i in range(len(chars))],
    }


class FakeProvider:
    """Returns audio bytes tagged with the call index so the fake transcription
    can decide whether that take stuttered."""
    def __init__(self):
        self.calls = 0
        self.seed = 0
        self.closed = False

    def signature(self):
        return "sig"

    def synthesize(self, text, prev, nxt, *, style=None):
        i = self.calls
        self.calls += 1
        return (f"take{i}".encode("ascii"), _fake_alignment(text))

    def close(self):
        self.closed = True


def test_heal_rerolls_until_clean_and_caches_good_take(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    provider = FakeProvider()
    monkeypatch.setattr(voice, "build_provider", lambda cfg, env: provider)
    # take0 stutters, take1 is clean.
    heard_by_take = {
        "take0": "حرية اختيار رد فعله تجاهه تجاه".split(),
        "take1": "حرية اختيار رد فعله تجاهه".split(),
    }
    monkeypatch.setattr(vv, "_transcribe_words_from_bytes",
                        lambda model, audio: heard_by_take[audio.decode("ascii")])

    out = vv.heal(project, {"voice": {"provider": "chatterbox"}}, {}, [2],
                  model="whisper-stub")

    assert out["all_fixed"] is True
    r = out["scenes"][0]
    assert r["id"] == 2 and r["fixed"] is True and r["attempts"] == 2
    assert provider.closed is True  # GPU worker released
    # The clean take is stored under scene 2's content-cache key.
    cache = project.path(voice.CACHE_DIR)
    mp3s = list(cache.glob("*.mp3"))
    assert len(mp3s) == 1 and mp3s[0].read_bytes() == b"take1"
    assert json.loads(mp3s[0].with_suffix(".json").read_text(encoding="utf-8"))


def test_heal_reports_unfixed_after_exhausting_tries(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    provider = FakeProvider()
    monkeypatch.setattr(voice, "build_provider", lambda cfg, env: provider)
    # Every take stutters.
    monkeypatch.setattr(vv, "_transcribe_words_from_bytes",
                        lambda model, audio: "حرية اختيار رد فعله تجاهه تجاه".split())

    out = vv.heal(project, {"voice": {"provider": "chatterbox"}}, {}, [2],
                  tries=3, model="stub")

    r = out["scenes"][0]
    assert r["fixed"] is False and r["attempts"] == 3
    assert out["all_fixed"] is False
    # Still leaves the last take cached (never no audio).
    assert list(project.path(voice.CACHE_DIR).glob("*.mp3"))


def test_heal_varies_pinned_seed_across_attempts(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    provider = FakeProvider()
    provider.seed = 7  # pinned seed -> must be varied so a re-roll differs
    seeds_seen = []
    orig = provider.synthesize

    def spy(text, prev, nxt, *, style=None):
        seeds_seen.append(provider.seed)
        return orig(text, prev, nxt, style=style)

    provider.synthesize = spy
    monkeypatch.setattr(voice, "build_provider", lambda cfg, env: provider)
    monkeypatch.setattr(vv, "_transcribe_words_from_bytes",
                        lambda model, audio: "حرية اختيار رد فعله تجاهه تجاه".split())

    vv.heal(project, {"voice": {"provider": "chatterbox"}}, {}, [2],
            tries=3, model="stub")

    assert seeds_seen == [8, 9, 10]          # 7+1+k, distinct per attempt
    assert provider.seed == 7                # restored afterwards


# -- fix: orchestration (audit -> heal -> rebuild -> re-audit) ---------------

def test_fix_heals_rebuilds_and_reaudits(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    reports = [
        {"repeat_scenes": [2], "low_similarity_scenes": []},        # before
        {"repeat_scenes": [], "low_similarity_scenes": [1]},        # after
    ]
    monkeypatch.setattr(vv, "audit",
                        lambda p, c, *, model=None, write=True: reports.pop(0))
    monkeypatch.setattr(vv, "_load_whisper", lambda cfg: "stub")
    heal_calls = {}
    monkeypatch.setattr(vv, "heal", lambda p, c, e, ids, *, tries=vv.DEFAULT_TRIES,
                        model=None: heal_calls.setdefault("ids", ids) or
                        {"scenes": [{"id": 2, "fixed": True, "attempts": 2}],
                         "all_fixed": True})
    rebuilt = {}
    monkeypatch.setattr(voice, "run",
                        lambda p, c, e, *, force=False: rebuilt.update(force=force))

    out = vv.fix(project, {"voice": {"provider": "chatterbox"}}, {})

    assert out["changed"] is True
    assert out["before_repeats"] == [2] and out["after_repeats"] == []
    assert heal_calls["ids"] == [2]
    assert rebuilt["force"] is True
    assert out["low_similarity"] == [1]


def test_fix_noop_when_clean(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    monkeypatch.setattr(vv, "audit", lambda p, c, *, model=None, write=True:
                        {"repeat_scenes": [], "low_similarity_scenes": []})
    monkeypatch.setattr(vv, "_load_whisper", lambda cfg: "stub")
    monkeypatch.setattr(vv, "heal", lambda *a, **k: pytest.fail("heal must not run"))
    monkeypatch.setattr(voice, "run", lambda *a, **k: pytest.fail("no rebuild"))

    out = vv.fix(project, {"voice": {"provider": "chatterbox"}}, {})

    assert out["changed"] is False and out["before_repeats"] == []
