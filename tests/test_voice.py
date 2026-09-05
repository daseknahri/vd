# -*- coding: utf-8 -*-
"""Voice stage tests. No network; TTS faked; ffprobe/concat patched in the
run() tests and exercised for real on tiny lavfi mp3s in one test."""

import base64
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import requests

from pipeline import contract, voice
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

CFG = {
    "voice": {
        "provider": "elevenlabs",
        "voice_id": "voice123",
        "model_id": "eleven_multilingual_v2",
        "stability": 0.5,
        "similarity_boost": 0.75,
        "speed": 1.0,
    }
}
ENV = {"ELEVENLABS_API_KEY": "key123"}

SCRIPT_DATA = {
    "meta": {
        "source_url": "https://example.com/v",
        "audience": "general Arab",
        "dialect": "MSA",
        "target_seconds": 90,
    },
    "hook": "لن تصدق ما حدث",
    "scenes": [
        {
            "id": 1,
            "narration_ar": "مرحبا بكم في المصنع",
            "keywords": [["factory interior"]],
            "mood": "calm",
            "target_seconds": 8,
        },
        {
            "id": 2,
            "narration_ar": "هذه خوارزمية، مذهلة حقا",
            "keywords": [["computer code closeup"]],
            "mood": "energetic",
            "target_seconds": 8,
        },
    ],
    "post": {"title": "t", "description": "d", "hashtags": ["#x"]},
}


def _fake_alignment(text):
    chars = list(text)
    return {
        "characters": chars,
        "character_start_times_seconds": [round(i * 0.1, 4) for i in range(len(chars))],
        "character_end_times_seconds": [round((i + 1) * 0.1, 4) for i in range(len(chars))],
    }


class FakeTTS:
    def __init__(self):
        self.calls = []
        self.styles = []

    def signature(self):
        return "fake-provider-sig"

    def synthesize(self, text, prev_text, next_text, *, style=None):
        self.calls.append((text, prev_text, next_text))
        self.styles.append(style)
        return ("MP3:" + text).encode("utf-8"), _fake_alignment(text)


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _stub_concat(scene_paths, out_path, workdir):
    out_path.write_bytes(b"".join(p.read_bytes() for p in scene_paths))


def _make_project(tmp_path, script=SCRIPT_DATA):
    d = tmp_path / "2026-06-12-test"
    d.mkdir()
    project = Project(dir=d)
    project.write_json(contract.SCRIPT, copy.deepcopy(script))
    return project


@pytest.fixture
def patched(monkeypatch):
    fake = FakeTTS()
    monkeypatch.setattr(voice, "_build_provider", lambda cfg, env: fake)
    monkeypatch.setattr(voice, "_probe_duration", lambda p: 2.0)
    monkeypatch.setattr(voice, "_concat_mp3s", _stub_concat)
    return fake


# -- run(): outputs, offsets, timing shape ----------------------------------

def test_run_writes_valid_timing_with_cumulative_offsets(tmp_path, patched):
    project = _make_project(tmp_path)
    voice.run(project, CFG, ENV)

    assert project.has(contract.VOICEOVER)
    timing = contract.validate_timing(project.read_json(contract.TIMING))

    assert timing["total_seconds"] == 4.0
    s1, s2 = timing["scenes"]
    assert (s1["id"], s1["start"], s1["end"]) == (1, 0.0, 2.0)
    assert (s2["id"], s2["start"], s2["end"]) == (2, 2.0, 4.0)

    # scene 1: "مرحبا" = chars 0..4 at 0.1s/char
    w0 = s1["words"][0]
    assert w0 == {"word": "مرحبا", "start": 0.0, "end": 0.5}
    assert [w["word"] for w in s1["words"]] == "مرحبا بكم في المصنع".split()
    # scene 2 word times are offset by scene 1's measured duration
    assert s2["words"][0]["start"] == 2.0
    assert all(w["start"] >= 2.0 for w in s2["words"])


def test_run_passes_neighbor_text_for_prosody(tmp_path, patched):
    project = _make_project(tmp_path)
    voice.run(project, CFG, ENV)

    (t1, prev1, next1), (t2, prev2, next2) = patched.calls
    assert prev1 == "" and next1 == t2
    assert prev2 == t1 and next2 == ""


def test_run_missing_script_raises_contract_error(tmp_path, patched):
    # Missing contracted input -> ContractError (consistent across stages).
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ContractError):
        voice.run(Project(dir=d), CFG, ENV)


# -- usage accounting (scene_characters + voice_report) ----------------------

def test_scene_characters_counts_spoken_text(tmp_path):
    project = _make_project(tmp_path)
    per_scene = voice.scene_characters(project.script(), {})
    assert [sid for sid, _ in per_scene] == [1, 2]
    assert dict(per_scene)[1] == len("مرحبا بكم في المصنع")
    assert dict(per_scene)[2] == len("هذه خوارزمية، مذهلة حقا")


def test_scene_characters_reflects_spoken_not_display(tmp_path):
    project = _make_project(tmp_path)
    plain = dict(voice.scene_characters(project.script(), {}))
    # A shorter respelling changes what is BILLED (spoken), scene 2 only.
    shortened = dict(voice.scene_characters(project.script(), {"خوارزمية": "خ"}))
    assert shortened[2] < plain[2]
    assert shortened[1] == plain[1]


def test_scene_characters_bad_override_raises(tmp_path):
    project = _make_project(tmp_path)
    with pytest.raises(ContractError, match="one word"):
        voice.scene_characters(project.script(), {"خوارزمية": "خوار زمية"})


def test_run_writes_voice_report_with_char_counts(tmp_path, patched):
    project = _make_project(tmp_path)
    voice.run(project, CFG, ENV)
    report = project.read_json(voice.VOICE_REPORT)
    total = len("مرحبا بكم في المصنع") + len("هذه خوارزمية، مذهلة حقا")
    assert report["total_characters"] == total
    assert report["billed_characters"] == total  # cold run -> everything billed
    assert [s["id"] for s in report["scenes"]] == [1, 2]
    assert report["scenes"][0]["characters"] == len("مرحبا بكم في المصنع")


# -- per-scene audio cache ---------------------------------------------------

def test_scene_audio_is_cached_across_reruns(tmp_path, patched):
    project = _make_project(tmp_path)
    voice.run(project, CFG, ENV)
    assert len(patched.calls) == 2

    # wipe the OUTPUTS but keep voice_cache/, then rebuild
    project.path(contract.VOICEOVER).unlink()
    project.path(contract.TIMING).unlink()
    voice.run(project, CFG, ENV)
    assert len(patched.calls) == 2          # no new API calls — served from cache
    assert project.has(contract.VOICEOVER)  # output still rebuilt
    assert project.read_json(voice.VOICE_REPORT)["billed_characters"] == 0


def test_force_reuses_cache_instead_of_rebilling(tmp_path, patched):
    project = _make_project(tmp_path)
    voice.run(project, CFG, ENV)
    n = len(patched.calls)
    assert n == 2
    voice.run(project, CFG, ENV)            # outputs exist -> early return
    assert len(patched.calls) == n
    # force rebuilds outputs but reuses cached scene audio (identical request):
    # no new API calls, so no re-billing.
    voice.run(project, CFG, ENV, force=True)
    assert len(patched.calls) == n
    assert project.has(contract.VOICEOVER) and project.has(contract.TIMING)


def test_clearing_cache_forces_fresh_synthesis(tmp_path, patched):
    project = _make_project(tmp_path)
    voice.run(project, CFG, ENV)
    assert len(patched.calls) == 2
    shutil.rmtree(project.path(voice._CACHE_DIR))
    voice.run(project, CFG, ENV, force=True)
    assert len(patched.calls) == 4  # cache gone -> both scenes re-synthesized


def test_editing_last_scene_reuses_unaffected_scene(tmp_path, patched):
    script = copy.deepcopy(SCRIPT_DATA)
    script["scenes"].append({
        "id": 3, "narration_ar": "المشهد الثالث هنا",
        "keywords": [["desk scene"]], "mood": "calm", "target_seconds": 8,
    })
    project = _make_project(tmp_path, script)
    voice.run(project, CFG, ENV)
    assert len(patched.calls) == 3

    edited = project.read_json(contract.SCRIPT)
    edited["scenes"][2]["narration_ar"] = "نص جديد مختلف للمشهد الثالث"
    project.write_json(contract.SCRIPT, edited)
    project.path(contract.VOICEOVER).unlink()
    project.path(contract.TIMING).unlink()
    voice.run(project, CFG, ENV)

    # scene 1 (text + neighbors unchanged) reused; scene 2's next_text changed
    # and scene 3's text changed, so only those two are re-synthesized.
    new_calls = patched.calls[3:]
    assert len(new_calls) == 2
    assert "نص جديد مختلف للمشهد الثالث" in {c[0] for c in new_calls}
    assert project.read_json(voice.VOICE_REPORT)["billed_characters"] == (
        len("هذه خوارزمية، مذهلة حقا") + len("نص جديد مختلف للمشهد الثالث"))


# -- pronunciation overrides -------------------------------------------------

def test_overrides_change_spoken_text_but_keep_display_words(tmp_path, patched):
    project = _make_project(tmp_path)
    project.write_json(contract.PRONUNCIATION, {"خوارزمية": "خوارِزْمِيَّة"})
    voice.run(project, CFG, ENV)

    spoken_scene2 = patched.calls[1][0]
    assert "خوارِزْمِيَّة،" in spoken_scene2          # respelling, comma kept
    assert "خوارزمية" not in spoken_scene2            # plain form gone
    timing = project.timing()
    display_words = [w["word"] for w in timing["scenes"][1]["words"]]
    assert "خوارزمية،" in display_words               # captions keep original
    assert len(display_words) == 4


def test_multiword_respelling_raises_contract_error(tmp_path, patched):
    project = _make_project(tmp_path)
    project.write_json(contract.PRONUNCIATION, {"خوارزمية": "خوار زمية"})
    with pytest.raises(ContractError, match="one word"):
        voice.run(project, CFG, ENV)


# -- idempotency --------------------------------------------------------------

def test_skip_needs_no_config_or_key(tmp_path):
    project = _make_project(tmp_path)
    project.path(contract.VOICEOVER).write_bytes(b"OLD")
    project.write_json(contract.TIMING, {
        "total_seconds": 1.0,
        "scenes": [{"id": 1, "start": 0.0, "end": 1.0, "words": []}],
    })
    voice.run(project, {"voice": {"voice_id": ""}}, {})  # must not raise
    assert project.path(contract.VOICEOVER).read_bytes() == b"OLD"


# -- config / env guards -------------------------------------------------------

def test_empty_voice_id_raises_contract_error(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    cfg = {"voice": {"voice_id": ""}}
    with pytest.raises(ContractError, match="voice_id"):
        voice.run(project, cfg, ENV)


def test_missing_api_key_raises_contract_error(tmp_path):
    project = _make_project(tmp_path)
    with pytest.raises(ContractError, match="ELEVENLABS_API_KEY"):
        voice.run(project, CFG, {})


# -- ElevenLabs provider -------------------------------------------------------

def test_elevenlabs_request_shape(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json, timeout=timeout)
        return FakeResponse(200, {
            "audio_base64": base64.b64encode(b"MP3DATA").decode("ascii"),
            "alignment": _fake_alignment("hi yo"),
        })

    monkeypatch.setattr(voice.requests, "post", fake_post)
    tts = voice.ElevenLabsTTS(api_key="k", voice_id="v123", model_id="m",
                              stability=0.4, similarity_boost=0.7, speed=1.1)
    audio, alignment = tts.synthesize("hi yo", "before", "after")

    assert audio == b"MP3DATA"
    assert alignment["characters"] == list("hi yo")
    assert captured["url"] == ("https://api.elevenlabs.io/v1/text-to-speech"
                               "/v123/with-timestamps")
    assert captured["headers"] == {"xi-api-key": "k"}
    assert captured["timeout"] == 30
    assert captured["body"] == {
        "text": "hi yo",
        "model_id": "m",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.7,
                           "speed": 1.1},
        "previous_text": "before",
        "next_text": "after",
    }


def test_post_retries_with_backoff_then_succeeds(monkeypatch):
    calls, sleeps = [], []
    monkeypatch.setattr(voice.time, "sleep", sleeps.append)

    def flaky_post(url, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise requests.ConnectionError("boom")
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(voice.requests, "post", flaky_post)
    assert voice._post_json("http://x", headers={}, body={}) == {"ok": True}
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_post_gives_up_after_three_attempts(monkeypatch):
    calls = []
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)

    def dead_post(url, **kwargs):
        calls.append(url)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(voice.requests, "post", dead_post)
    with pytest.raises(StageError):
        voice._post_json("http://x", headers={}, body={})
    assert len(calls) == 3


def test_post_fails_fast_on_auth_error(monkeypatch):
    calls = []

    def post_401(url, **kwargs):
        calls.append(url)
        return FakeResponse(401, text="bad key")

    monkeypatch.setattr(voice.requests, "post", post_401)
    with pytest.raises(StageError, match="401"):
        voice._post_json("http://x", headers={}, body={})
    assert len(calls) == 1


# -- word grouping -------------------------------------------------------------

def test_words_from_alignment_groups_and_offsets():
    text = "أهلا وسهلا بكم"
    words = voice._words_from_alignment(text, _fake_alignment(text), 10.0)
    assert [w["word"] for w in words] == ["أهلا", "وسهلا", "بكم"]
    assert words[0]["start"] == 10.0 and words[0]["end"] == 10.4
    assert words[1]["start"] == 10.5  # after the space char
    assert all(w["end"] > w["start"] for w in words)


def test_words_from_alignment_mismatch_raises_stage_error():
    with pytest.raises(StageError, match="alignment"):
        voice._words_from_alignment("كلمة واحدة زيادة",
                                    _fake_alignment("كلمتان فقط"), 0.0)


# -- real ffmpeg on tiny synthetic inputs --------------------------------------

def test_concat_and_probe_real_ffmpeg(tmp_path):
    ffmpeg = contract.ffmpeg_path("ffmpeg")
    pieces = []
    for name, freq in (("a.mp3", 440), ("b.mp3", 660)):
        p = tmp_path / name
        subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=0.3",
             "-c:a", "libmp3lame", str(p)],
            check=True, capture_output=True,
        )
        pieces.append(p)

    out = tmp_path / "voiceover.mp3"
    voice._concat_mp3s(pieces, out, tmp_path)
    assert out.exists() and out.stat().st_size > 0
    assert 0.45 <= voice._probe_duration(out) <= 0.9  # ~0.6s + mp3 padding


def test_concat_handles_apostrophe_in_path(tmp_path):
    """Windows user folders like O'Brien are legal; the concat list must
    escape the quote or ffmpeg truncates the file directive."""
    ffmpeg = contract.ffmpeg_path("ffmpeg")
    work = tmp_path / "o'brien"
    work.mkdir()
    p = work / "a.mp3"
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
         "-c:a", "libmp3lame", str(p)],
        check=True, capture_output=True,
    )
    out = work / "voiceover.mp3"
    voice._concat_mp3s([p], out, work)
    assert out.exists() and out.stat().st_size > 0


def test_concat_with_relative_input_path(tmp_path, monkeypatch):
    """Regression: `run.py process projects\\<slug>` makes scene paths project-
    relative. The concat list must hold ABSOLUTE paths, else ffmpeg's demuxer
    resolves them against the list file's own dir and doubles them
    (voice_tmp/proj/voice_tmp/scene_001.mp3 -> not found)."""
    ffmpeg = contract.ffmpeg_path("ffmpeg")
    monkeypatch.chdir(tmp_path)
    work = Path("proj") / "voice_tmp"
    work.mkdir(parents=True)
    p = work / "scene_001.mp3"          # relative path, as the live pipeline uses
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
         "-c:a", "libmp3lame", str(p)],
        check=True, capture_output=True,
    )
    out = work / "voiceover.mp3"
    voice._concat_mp3s([p], out, work)  # would fail on the doubled path pre-fix
    assert out.exists() and out.stat().st_size > 0


def test_subprocess_decodes_utf8_with_replacement(tmp_path, monkeypatch):
    """ffmpeg/ffprobe output must be decoded as UTF-8 with errors=replace —
    Windows locale codepages raise UnicodeDecodeError on stray bytes."""
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "1.5\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(voice.subprocess, "run", fake_run)
    assert voice._probe_duration(tmp_path / "x.mp3") == 1.5
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"

    captured.clear()
    voice._concat_mp3s([tmp_path / "a.mp3"], tmp_path / "out.mp3", tmp_path)
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


# -- per-scene expressive delivery + designed pauses ---------------------------

_DELIVERY = {
    "by_mood": {
        "energetic": {"exaggeration": 0.70, "cfg_weight": 0.42, "pause_after": 0.45},
        "calm": {"exaggeration": 0.42, "cfg_weight": 0.58, "pause_after": 0.70},
        "archival": {"exaggeration": 0.38, "cfg_weight": 0.60, "pause_after": 0.85},
    },
    "default": {"exaggeration": 0.5, "cfg_weight": 0.5, "pause_after": 0.55},
    "mood_shift_pause": 1.2,
    "max_pause": 2.5,
}


def test_delivery_for_scene_maps_mood_to_style_and_pause():
    style, pause = voice._delivery_for_scene(
        {"mood": "energetic"}, "energetic", _DELIVERY)
    assert style == {"exaggeration": 0.70, "cfg_weight": 0.42}
    assert pause == 0.45


def test_delivery_none_when_unconfigured():
    # no voice.delivery -> feature inert (old behavior): no style, no pause
    assert voice._delivery_for_scene({"mood": "calm"}, None, None) == (None, 0.0)
    assert voice._delivery_for_scene({"mood": "calm"}, None, {}) == (None, 0.0)


def test_delivery_mood_shift_bumps_pause():
    # calm's own pause is 0.70, but the next scene changes mood -> section break
    _, pause = voice._delivery_for_scene({"mood": "calm"}, "energetic", _DELIVERY)
    assert pause == 1.2
    # same mood next -> keep the mood's own pause
    _, pause_same = voice._delivery_for_scene({"mood": "calm"}, "calm", _DELIVERY)
    assert pause_same == 0.70


def test_delivery_caps_pause_at_max():
    dcfg = dict(_DELIVERY, mood_shift_pause=99.0, max_pause=2.5)
    _, pause = voice._delivery_for_scene({"mood": "archival"}, "calm", dcfg)
    assert pause == 2.5


def test_cache_key_includes_style():
    base = ("sig", "text", "prev", "next")
    k0 = voice._cache_key(*base, None)
    k1 = voice._cache_key(*base, {"exaggeration": 0.7, "cfg_weight": 0.3})
    k2 = voice._cache_key(*base, {"exaggeration": 0.4, "cfg_weight": 0.6})
    assert k0 != k1 != k2 and k0 != k2   # each delivery caches separately


def test_run_delivery_passes_per_scene_style_and_folds_pauses(tmp_path, monkeypatch):
    fake = FakeTTS()
    monkeypatch.setattr(voice, "_build_provider", lambda cfg, env: fake)
    monkeypatch.setattr(voice, "_concat_mp3s", _stub_concat)
    monkeypatch.setattr(voice, "_probe_duration", lambda p: 2.0)
    pads = []
    monkeypatch.setattr(voice, "_append_silence",
                        lambda path, secs: pads.append((path.name, round(secs, 3))))
    cfg = {"voice": {"provider": "chatterbox", "chatterbox": {"language": "ar"},
                     "delivery": _DELIVERY}}
    project = _make_project(tmp_path)  # scene1 calm, scene2 energetic
    voice.run(project, cfg, {})

    # scene 1 (calm) delivered with calm params; scene 2 (energetic) with its own
    assert fake.styles == [
        {"exaggeration": 0.42, "cfg_weight": 0.58},
        {"exaggeration": 0.70, "cfg_weight": 0.42},
    ]
    # scene1->scene2 is a mood shift -> 1.2s breath; scene2 is last -> its 0.45s
    assert pads == [("scene_001.mp3", 1.2), ("scene_002.mp3", 0.45)]


def test_append_silence_adds_trailing_silence_real_ffmpeg(tmp_path):
    ffmpeg = contract.ffmpeg_path("ffmpeg")
    p = tmp_path / "s.mp3"
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
         "-c:a", "libmp3lame", str(p)],
        check=True, capture_output=True,
    )
    before = voice._probe_duration(p)
    voice._append_silence(p, 0.6)
    after = voice._probe_duration(p)
    assert after >= before + 0.5   # ~0.6s of silence appended (allow mp3 slop)


def test_append_silence_zero_is_noop(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(voice.subprocess, "run",
                        lambda *a, **k: called.append(a))
    voice._append_silence(tmp_path / "x.mp3", 0.0)
    assert called == []   # no ffmpeg invocation for a zero pause
