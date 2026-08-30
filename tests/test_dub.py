"""Tests for the dub workflow logic (pipeline/dub.py) + the thin scripts.

No network, no real TTS/whisper/ffmpeg — every function under test is pure.
Narration strings are ASCII placeholders (validate_script only requires a
non-empty string; the real Arabic lives in project files, not tests)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from pipeline import contract, dub, render_ffmpeg, voice
from pipeline.contract import ContractError, Project

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- segmentation
def words(*pairs):
    """(text, start, end) tuples -> whisper-style word dicts."""
    return [{"t": t, "start": s, "end": e} for t, s, e in pairs]


def test_norm_word_drops_apostrophes_and_case():
    assert dub.norm_word("Let's") == "lets"
    assert dub.norm_word("Shadowing,") == "shadowing"


def test_find_story_end_matches_contraction_marker():
    stream = ["now", "lets", "do", "some", "shadowing", "together"]
    assert dub.find_story_end(stream, "now lets do some shadowing") == 0
    assert dub.find_story_end(["a", "b"], "now lets") == 2  # not found -> len


def test_group_sentences_splits_on_punct_and_maxlen():
    segs = dub.group_sentences(
        words(("Hello", 0.0, 0.5), ("world.", 0.5, 1.0),
              ("A", 1.0, 8.5)),  # 7.5s running -> forced split
        max_s=7.0)
    assert [s["en"] for s in segs] == ["Hello world.", "A"]
    assert segs[0]["id"] == 1 and segs[1]["id"] == 2


def test_build_segments_marker_found_truncates_story():
    stream = words(("In", 0.0, 0.5), ("Verona.", 0.5, 1.0),
                   ("Now", 1.0, 1.5), ("lets", 1.5, 2.0),
                   ("do", 2.0, 2.5), ("some", 2.5, 3.0),
                   ("shadowing", 3.0, 3.5))
    out = dub.build_segments(stream, "now lets do some shadowing", 7.0)
    assert out["marker_found"] is True
    assert out["story_end"] == 1.0  # cut before "Now"
    assert out["segments"][0]["en"] == "In Verona."


def test_build_segments_marker_absent_uses_whole_and_flags():
    stream = words(("Only", 0.0, 0.5), ("story.", 0.5, 1.0))
    out = dub.build_segments(stream, "never appears here", 7.0)
    assert out["marker_found"] is False
    assert out["story_end"] == 1.0


# --------------------------------------------------------------------- refine
def _raw(*ens):
    segs = [{"id": i + 1, "en": e, "start": float(i), "end": float(i + 1)}
            for i, e in enumerate(ens)]
    return {"segments": segs}


def test_refine_merges_fragments_into_sentences():
    out = dub.refine_segments(_raw("A,", "B.", "C."), 1, 3)
    assert [s["en"] for s in out["segments"]] == ["A, B.", "C."]
    assert out["story_start"] == 0.0 and out["story_end"] == 3.0
    assert out["segments"][0]["id"] == 1 and out["segments"][1]["id"] == 2


def test_refine_respects_id_range():
    out = dub.refine_segments(_raw("A.", "B.", "C."), 2, 3)
    assert [s["en"] for s in out["segments"]] == ["B.", "C."]


def test_refine_empty_range_raises_contract_error():
    with pytest.raises(ContractError):
        dub.refine_segments(_raw("A.", "B."), 5, 9)


# --------------------------------------------------------------- build_script
def _segs():
    return {"story_start": 5.0, "story_end": 15.0,
            "segments": [{"id": 1, "start": 5.0, "end": 9.0, "en": "x"},
                         {"id": 2, "start": 9.0, "end": 15.0, "en": "y"}]}


def _translations(**over):
    base = {
        "dialect": "MSA",
        "post": {"title": "T", "description": "D", "hashtags": ["#a"]},
        "translations": {"1": "ar-one", "2": "ar-two"},
    }
    base.update(over)
    return base


def test_build_script_is_contract_valid_with_slot_durations():
    script = dub.build_script(_segs(), _translations(), "http://src")
    contract.validate_script(script)  # raises if invalid
    assert script["meta"]["workflow"] == "dub"
    assert script["meta"]["source_url"] == "http://src"
    assert script["meta"]["target_seconds"] == 10.0
    assert [s["target_seconds"] for s in script["scenes"]] == [4.0, 6.0]
    assert script["post"]["title"] == "T"
    assert script["hook"] == "ar-one"


def test_build_script_source_url_from_translations_when_arg_blank():
    tr = _translations(source_url="http://from-json")
    assert dub.build_script(_segs(), tr, "")["meta"]["source_url"] == "http://from-json"


def test_build_script_missing_source_url_raises():
    with pytest.raises(ContractError):
        dub.build_script(_segs(), _translations(), "")


def test_build_script_missing_translation_raises():
    tr = _translations(translations={"1": "only-one"})
    with pytest.raises(ContractError):
        dub.build_script(_segs(), tr, "http://src")


def test_build_script_missing_post_raises():
    tr = _translations()
    del tr["post"]
    with pytest.raises(ContractError):
        dub.build_script(_segs(), tr, "http://src")


# ------------------------------------------------------------- dryrun timing
def test_build_dryrun_timing_places_scenes_in_slots():
    script = dub.build_script(_segs(), _translations(), "http://src")
    timing = dub.build_dryrun_timing(script, _segs())
    contract.validate_timing(timing)
    assert timing["total_seconds"] == 10.0
    assert timing["scenes"][0] == {"id": 1, "start": 0.0, "end": 4.0, "words": []}
    assert timing["scenes"][1]["start"] == 4.0 and timing["scenes"][1]["end"] == 10.0


# -------------------------------------------------------------- place_scenes
def test_place_scenes_natural_speed_when_it_fits():
    plan = dub.place_scenes([1.0, 1.0], [0.0, 2.0], 4.0)
    assert plan["overruns"] == []
    assert [p["speed"] for p in plan["placements"]] == [1.0, 1.0]
    assert plan["placements"][0]["delay_ms"] == 0
    assert plan["placements"][1]["delay_ms"] == 2000
    assert plan["total"] == 4.0


def test_place_scenes_speeds_up_within_cap():
    # dur 2.5 into a 2.0 slot -> 1.25x (<= cap 1.3), fits exactly, no overrun.
    plan = dub.place_scenes([2.5], [0.0], 2.0)
    assert plan["placements"][0]["speed"] == pytest.approx(1.25)
    assert plan["overruns"] == []


def test_place_scenes_flags_overrun_past_cap_and_pushes():
    # dur 3.0 into a 1.0 slot -> capped at 1.3x, still overruns; scene 2 pushed.
    plan = dub.place_scenes([3.0, 1.0], [0.0, 1.0], 5.0)
    assert plan["placements"][0]["speed"] == pytest.approx(1.3)
    assert plan["overruns"] == [0]
    assert plan["placements"][1]["start"] > 1.0  # pushed past its slot start


def test_place_scenes_length_mismatch_raises():
    with pytest.raises(ValueError):
        dub.place_scenes([1.0], [0.0, 1.0], 5.0)


# ----------------------------------------------------------- render filtergraph
def _band():
    return {"width": 1280, "height": 114, "y": 556}


def test_render_filtergraph_default_cover_and_no_watermark():
    graph, vlabel, report = dub.render_filtergraph(
        1280, 720, 30, 100.0, _band(), {}, has_captions=True)
    assert "delogo" not in graph
    assert "drawbox=x=0:y=544:w=1280:h=176" in graph  # 720-544, default top
    assert vlabel == "[vout]" and "overlay=x=0:y=556" in graph
    assert report["watermark_removed"] is False


def test_render_filtergraph_watermark_and_custom_band_no_captions():
    dcfg = {"cover_top": 500, "cover_bottom": 690,
            "watermark": {"x": 1126, "y": 12, "w": 116, "h": 112}}
    graph, vlabel, report = dub.render_filtergraph(
        1280, 720, 30, 50.0, _band(), dcfg, has_captions=False)
    assert "delogo=x=1126:y=12:w=116:h=112" in graph
    assert "drawbox=x=0:y=500:w=1280:h=190" in graph  # 690-500
    assert vlabel == "[base]" and "overlay" not in graph
    assert report["cover_band"] == {"top": 500, "bottom": 690, "color": "black"}
    assert report["watermark_removed"] is True


# ------------------------------------------------------------- load_segments
def test_load_segments_prefers_refined(tmp_path):
    project = Project(dir=tmp_path)
    project.write_json(dub.SEGMENTS, {"segments": [{"id": 1}], "tag": "raw"})
    project.write_json(dub.SEGMENTS_REFINED, {"segments": [{"id": 1}], "tag": "refined"})
    assert dub.load_segments(project)["tag"] == "refined"
    (tmp_path / dub.SEGMENTS_REFINED).unlink()
    assert dub.load_segments(project)["tag"] == "raw"


def test_load_segments_missing_raises(tmp_path):
    with pytest.raises(ContractError):
        dub.load_segments(Project(dir=tmp_path))


# -------------------------------------------------- guard: public reuse surface
def test_voice_and_render_public_aliases_exist_and_callable():
    for fn in (voice.build_provider, voice.synthesize_cached,
               voice.probe_duration, voice.words_from_alignment,
               render_ffmpeg.load_manifest, render_ffmpeg.build_caption_track,
               render_ffmpeg.probe):
        assert callable(fn)
    assert voice.build_provider is voice._build_provider


@pytest.mark.parametrize("name", [
    "dub_segment", "dub_refine_segments", "dub_build_script", "dub_review",
    "dub_voice", "dub_dryrun", "dub_render",
])
def test_dub_scripts_import_and_expose_main(name):
    """Each thin script imports cleanly (no whisper/ffmpeg at import time) and
    exposes main() — a refactor that breaks a dub script's import fails here."""
    spec = importlib.util.spec_from_file_location(
        f"_dubscript_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
