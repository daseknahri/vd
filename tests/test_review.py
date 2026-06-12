# -*- coding: utf-8 -*-
"""Review stage tests. Real ffmpeg runs once on a tiny lavfi clip; the
remaining tests stub thumbnail extraction."""

import copy
import html
import subprocess

import pytest

from pipeline import contract, review
from pipeline.contract import ContractError, Project

SCRIPT_DATA = {
    "meta": {
        "source_url": "https://example.com/v",
        "audience": "general Arab",
        "dialect": "MSA",
        "target_seconds": 24,
    },
    "hook": "لن تصدق ما ستراه الآن",
    "scenes": [
        {
            "id": 1,
            "narration_ar": "مدينة عملاقة وسط الصحراء",
            "keywords": [["aerial desert city"], ["desert skyline sunset"]],
            "mood": "calm",
            "target_seconds": 8,
        },
        {
            "id": 2,
            "narration_ar": "روبوتات تبني الأبراج بسرعة مذهلة",
            "keywords": [["construction robots"]],
            "mood": "energetic",
            "target_seconds": 8,
        },
        {
            "id": 3,
            "narration_ar": "لقطات أرشيفية من بداية المشروع",
            "keywords": [["archival construction footage"]],
            "mood": "archival",
            "target_seconds": 8,
        },
    ],
    "post": {"title": "t", "description": "d", "hashtags": []},
}


def _make_project(tmp_path):
    d = tmp_path / "2026-06-12-test"
    d.mkdir()
    project = Project(dir=d)
    project.write_json(contract.SCRIPT, copy.deepcopy(SCRIPT_DATA))
    return project


def _fake_clip(project, scene_id):
    p = project.clips_dir / f"scene_{scene_id:03d}.mp4"
    p.write_bytes(b"MP4")
    return p


@pytest.fixture
def stub_thumbs(monkeypatch):
    """Replace ffmpeg thumbnail extraction; records scene ids handled."""
    made = []

    def stub(project, scene_id, clip, *, force):
        thumbs = project.path(review.THUMBS_DIR)
        thumbs.mkdir(exist_ok=True)
        out = thumbs / f"scene_{scene_id:03d}.jpg"
        out.write_bytes(b"JPG")
        made.append(scene_id)
        return f"{review.THUMBS_DIR}/{out.name}"

    monkeypatch.setattr(review, "_make_thumbnail", stub)
    return made


# -- full run with real ffmpeg on a lavfi clip --------------------------------

def test_run_real_ffmpeg_full_sheet(tmp_path):
    project = _make_project(tmp_path)
    clip = project.clips_dir / "scene_001.mp4"
    subprocess.run(
        [contract.ffmpeg_path("ffmpeg"), "-y", "-hide_banner",
         "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=red:s=640x360:d=0.5:r=12",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True,
    )
    project.write_json(review.FOOTAGE_REPORT, {
        "flagged": [{"id": 2, "reason": "no acceptable match"}],
    })
    # scene 3 has no clip at all -> flagged too

    review.run(project, {}, {})

    sheet = project.read_text(contract.CONTACT_SHEET)
    assert 'dir="rtl"' in sheet and 'lang="ar"' in sheet
    assert '<meta charset="utf-8">' in sheet
    for scene in SCRIPT_DATA["scenes"]:
        assert scene["narration_ar"] in sheet
    assert sheet.count("FLAGGED") == 2          # scene 2 (report) + 3 (no clip)
    assert "no acceptable match" in sheet
    assert "thumbs/scene_001.jpg" in sheet

    thumb = project.path(review.THUMBS_DIR) / "scene_001.jpg"
    assert thumb.exists()
    from PIL import Image
    with Image.open(thumb) as im:
        assert im.width == review.THUMB_WIDTH


# -- structure / content (thumbnails stubbed) ---------------------------------

def test_clean_sheet_has_keywords_and_no_flags(tmp_path, stub_thumbs):
    project = _make_project(tmp_path)
    for sid in (1, 2, 3):
        _fake_clip(project, sid)
    review.run(project, {}, {})

    sheet = project.read_text(contract.CONTACT_SHEET)
    assert "FLAGGED" not in sheet
    assert "aerial desert city" in sheet
    assert "desert skyline sunset" in sheet     # fallback set shown too
    assert "<script" not in sheet.lower()       # no JS dependencies
    assert stub_thumbs == [1, 2, 3]


def test_target_vs_actual_seconds_from_timing(tmp_path, stub_thumbs):
    project = _make_project(tmp_path)
    for sid in (1, 2, 3):
        _fake_clip(project, sid)
    project.write_json(contract.TIMING, {
        "total_seconds": 21.5,
        "scenes": [
            {"id": 1, "start": 0.0, "end": 7.4, "words": []},
            {"id": 2, "start": 7.4, "end": 14.2, "words": []},
            {"id": 3, "start": 14.2, "end": 21.5, "words": []},
        ],
    })
    review.run(project, {}, {})
    sheet = project.read_text(contract.CONTACT_SHEET)
    assert "target 8s · actual 7.4s" in sheet
    assert "actual 6.8s" in sheet


def test_no_timing_shows_dash_for_actual(tmp_path, stub_thumbs):
    project = _make_project(tmp_path)
    for sid in (1, 2, 3):
        _fake_clip(project, sid)
    review.run(project, {}, {})
    sheet = project.read_text(contract.CONTACT_SHEET)
    assert "actual —" in sheet


def test_footer_has_runnable_redo_and_approve_commands(tmp_path, stub_thumbs):
    """The printed commands must work when pasted from the repo root, so
    they carry the full quoted project path — not the bare folder name
    (which only resolves when CWD happens to be projects/)."""
    project = _make_project(tmp_path)
    for sid in (1, 2, 3):
        _fake_clip(project, sid)
    review.run(project, {}, {})
    sheet = project.read_text(contract.CONTACT_SHEET)
    target = html.escape(f'"{project.dir}"')
    assert f"python run.py redo {target} --scenes" in sheet
    assert f"python run.py approve {target} --gate 2" in sheet


def test_footer_redo_lists_flagged_scene_ids(tmp_path, stub_thumbs):
    project = _make_project(tmp_path)
    _fake_clip(project, 1)                      # scenes 2 + 3 have no clip
    review.run(project, {}, {})
    sheet = project.read_text(contract.CONTACT_SHEET)
    target = html.escape(f'"{project.dir}"')
    assert f"redo {target} --scenes 2 3" in sheet


# -- flag sources --------------------------------------------------------------

def test_render_report_also_flags(tmp_path, stub_thumbs):
    project = _make_project(tmp_path)
    for sid in (1, 2, 3):
        _fake_clip(project, sid)
    project.write_json(review.RENDER_REPORT, {
        "scenes": [{"id": 3, "status": "failed"}],
    })
    review.run(project, {}, {})
    sheet = project.read_text(contract.CONTACT_SHEET)
    assert sheet.count("FLAGGED") == 1
    assert "render_report.json: failed" in sheet


def test_report_shapes_parse():
    src = "footage_report.json"
    assert set(review._flagged_in_report({"flagged": [2, 5]}, src)) == {2, 5}
    assert review._flagged_in_report(
        {"flagged": [{"id": 4, "reason": "placeholder used"}]}, src
    ) == {4: f"{src}: placeholder used"}
    assert set(review._flagged_in_report(
        {"scenes": [{"id": 1, "status": "ok"},
                    {"id": 2, "status": "unmatched"},
                    {"scene_id": 3, "flagged": True}]}, src
    )) == {2, 3}
    assert set(review._flagged_in_report(
        [{"scene": 7, "placeholder": True}], src
    )) == {7}
    assert review._flagged_in_report(
        {"scenes": [{"id": 1, "status": "matched"}]}, src
    ) == {}


def test_corrupt_report_raises_contract_error(tmp_path, stub_thumbs):
    project = _make_project(tmp_path)
    _fake_clip(project, 1)
    project.write_text(review.FOOTAGE_REPORT, "{not json")
    with pytest.raises(ContractError, match="not valid JSON"):
        review.run(project, {}, {})


# -- idempotency / errors --------------------------------------------------------

def test_idempotent_skip_and_force_rerun(tmp_path, stub_thumbs):
    project = _make_project(tmp_path)
    for sid in (1, 2, 3):
        _fake_clip(project, sid)
    review.run(project, {}, {})
    assert len(stub_thumbs) == 3

    project.write_text(contract.CONTACT_SHEET, "OLD")
    review.run(project, {}, {})                 # output exists -> early return
    assert project.read_text(contract.CONTACT_SHEET) == "OLD"
    assert len(stub_thumbs) == 3

    review.run(project, {}, {}, force=True)
    assert 'dir="rtl"' in project.read_text(contract.CONTACT_SHEET)
    assert len(stub_thumbs) == 6


def test_missing_script_raises_contract_error(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ContractError, match="script.json"):
        review.run(Project(dir=d), {}, {})


def test_subprocess_decodes_utf8_with_replacement(tmp_path, monkeypatch):
    """ffprobe output must be decoded as UTF-8 with errors=replace —
    Windows locale codepages raise UnicodeDecodeError on stray bytes."""
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "2.0\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(review.subprocess, "run", fake_run)
    assert review._probe_duration(tmp_path / "clip.mp4") == 2.0
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


# -- thumbnail idempotency (no ffmpeg call when jpg exists) ---------------------

def test_existing_thumbnail_skips_ffmpeg(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    clip = _fake_clip(project, 1)
    thumbs = project.path(review.THUMBS_DIR)
    thumbs.mkdir()
    (thumbs / "scene_001.jpg").write_bytes(b"JPG")

    def boom(*a, **k):
        raise AssertionError("ffmpeg must not run")

    monkeypatch.setattr(review.subprocess, "run", boom)
    rel = review._make_thumbnail(project, 1, clip, force=False)
    assert rel == "thumbs/scene_001.jpg"
