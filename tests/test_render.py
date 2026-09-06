"""Tests for pipeline/render_ffmpeg.py.

Real ffmpeg on tiny lavfi-generated inputs (320x568@15fps, 4 seconds);
no network. The expensive full render runs once in a session fixture.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from pipeline import contract, render_ffmpeg
from pipeline.contract import ContractError, Project

FFMPEG = contract.ffmpeg_path("ffmpeg")
W, H, FPS = 320, 568, 15
BAND_H = 80
TOTAL = 4.0

SCRIPT = {
    "meta": {"source_url": "https://example.com/v", "audience": "general Arab",
             "dialect": "MSA", "target_seconds": 4},
    "hook": "خطاف تجريبي",
    "scenes": [
        {"id": 1, "narration_ar": "مرحبا بكم في الاختبار",
         "keywords": [["city night"]], "mood": "calm", "target_seconds": 2},
        {"id": 2, "narration_ar": "إلى اللقاء",
         "keywords": [["desert road"]], "mood": "calm", "target_seconds": 2},
    ],
    "post": {"title": "t", "description": "d", "hashtags": []},
}

TIMING = {
    "total_seconds": TOTAL,
    "scenes": [
        {"id": 1, "start": 0.0, "end": 2.0, "words": []},
        {"id": 2, "start": 2.0, "end": 4.0, "words": []},
    ],
}


def _cfg(music_dir: str) -> dict:
    return {
        "video": {"width": W, "height": H, "fps": FPS},
        "audio": {"music_dir": music_dir, "music_gain_db": -14,
                  "duck_threshold": 0.05, "duck_ratio": 8,
                  "loudness_lufs": -16},
        "captions": {"margin_v": BAND_H},
    }


def _make_project(root: Path, *, with_captions: bool = True) -> Project:
    proj = Project(dir=root / "p")
    proj.dir.mkdir(parents=True)
    proj.write_json(contract.SCRIPT, SCRIPT)
    proj.write_json(contract.TIMING, TIMING)
    # clip for scene 1 only; scene 2 stays missing -> placeholder path
    clip = proj.clips_dir / "scene_001.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration=2",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(clip)],
        check=True, capture_output=True)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={TOTAL}",
         "-c:a", "libmp3lame", "-b:a", "64k",
         str(proj.path(contract.VOICEOVER))],
        check=True, capture_output=True)
    if with_captions:
        cap_dir = proj.dir / render_ffmpeg.CAPTIONS_DIR
        cap_dir.mkdir()
        for i, color in ((1, (255, 0, 0, 200)), (2, (0, 255, 0, 200))):
            Image.new("RGBA", (W, BAND_H), color).save(
                cap_dir / f"cap_{i:04d}.png")
        manifest = {
            "band": {"width": W, "height": BAND_H, "y": 400},
            "entries": [
                {"png": "cap_0001.png", "start": 0.2, "end": 1.0},
                {"png": "cap_0002.png", "start": 2.5, "end": 3.4},
            ],
        }
        (cap_dir / render_ffmpeg.CAPTIONS_MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return proj


def _probe(path: Path) -> dict:
    proc = subprocess.run(
        [contract.ffmpeg_path("ffprobe"), "-v", "error", "-print_format",
         "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(proc.stdout)


@pytest.fixture(scope="session")
def rendered(tmp_path_factory) -> tuple[Project, dict]:
    root = tmp_path_factory.mktemp("render")
    proj = _make_project(root)
    cfg = _cfg(str(root / "no_music_dir"))  # missing dir -> voice only
    render_ffmpeg.run(proj, cfg, {}, force=False)
    return proj, cfg


# --------------------------------------------------------------------------
# Full render (real ffmpeg)
# --------------------------------------------------------------------------

def test_final_mp4_duration_and_resolution(rendered):
    proj, _ = rendered
    final = proj.path(contract.FINAL)
    assert final.exists()
    data = _probe(final)
    duration = float(data["format"]["duration"])
    assert abs(duration - TOTAL) <= 0.5
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (W, H)
    assert any(s["codec_type"] == "audio" for s in data["streams"])


def test_report_records_scenes_placeholder_and_probe(rendered):
    proj, _ = rendered
    report = proj.read_json(render_ffmpeg.RENDER_REPORT)

    scenes = {row["id"]: row for row in report["scenes"]}
    assert scenes[1]["placeholder"] is False
    assert scenes[1]["clip"] == "clips/scene_001.mp4"
    assert scenes[1]["duration"] == pytest.approx(2.0)
    assert scenes[2]["placeholder"] is True
    assert scenes[2]["clip"] is None
    assert report["gaps"] == [2]

    assert report["captions"]["pages"] == 2
    # gaps: 0-0.2, 1.0-2.5, 3.4-4.0
    assert report["captions"]["gap_entries"] == 3
    assert report["music"] is None
    assert len(report["commands"]) >= 2  # captions encode + final + probe
    assert abs(report["output"]["duration"] - TOTAL) <= 0.5
    assert (report["output"]["width"], report["output"]["height"]) == (W, H)


def test_idempotent_unless_forced(rendered):
    proj, cfg = rendered
    final = proj.path(contract.FINAL)
    before = final.stat().st_mtime_ns
    render_ffmpeg.run(proj, cfg, {}, force=False)
    assert final.stat().st_mtime_ns == before


def test_final_ffmpeg_command_shape(rendered):
    proj, _ = rendered
    report = proj.read_json(render_ffmpeg.RENDER_REPORT)
    final_cmd = next(c for c in report["commands"]
                     if str(proj.path(contract.FINAL)) in c)
    fc = final_cmd[final_cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[vcat]" in fc
    assert "scale=320:568:force_original_aspect_ratio=increase,crop=320:568" in fc
    assert "overlay=x=0:y=400:shortest=1" in fc
    assert f"color=c={render_ffmpeg.PLACEHOLDER_COLOR}" in " ".join(final_cmd)
    assert "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]" in fc
    for flag in ("libx264", "yuv420p", "+faststart", "aac"):
        assert flag in final_cmd


def test_pop_in_icon_overlaid_and_renders(tmp_path):
    """A scene with an `icon` adds a timed, faded-in overlay of the real icon
    asset to the render, and still produces a valid final.mp4."""
    import copy
    proj = _make_project(tmp_path)
    script = copy.deepcopy(SCRIPT)
    script["scenes"][0]["icon"] = "question"   # assets/icons/question.png
    proj.write_json(contract.SCRIPT, script)
    render_ffmpeg.run(proj, _cfg(str(tmp_path / "no_music")), {}, force=True)

    report = proj.read_json(render_ffmpeg.RENDER_REPORT)
    final_cmd = next(c for c in report["commands"]
                     if str(proj.path(contract.FINAL)) in c)
    joined = " ".join(final_cmd)
    assert "question.png" in joined                  # icon input added
    fc = final_cmd[final_cmd.index("-filter_complex") + 1]
    assert "fade=t=in:st=" in fc                      # pop/fade-in
    assert "enable='between(t," in fc                 # timed to the scene beat
    assert proj.path(contract.FINAL).exists()         # rendered for real


def test_render_with_music_bed_and_empty_manifest(tmp_path):
    """Music graph (aloop/duck/amix) runs for real; no overlay when the
    manifest has no entries."""
    proj = _make_project(tmp_path, with_captions=False)
    cap_dir = proj.dir / render_ffmpeg.CAPTIONS_DIR
    cap_dir.mkdir()
    (cap_dir / render_ffmpeg.CAPTIONS_MANIFEST).write_text(
        '{"band": null, "entries": []}', encoding="utf-8")
    music = tmp_path / "music"
    music.mkdir()
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=220:duration=1",
         str(music / "bed.wav")],
        check=True, capture_output=True)
    render_ffmpeg.run(proj, _cfg(str(music)), {})

    final = proj.path(contract.FINAL)
    data = _probe(final)
    assert abs(float(data["format"]["duration"]) - TOTAL) <= 0.5
    report = proj.read_json(render_ffmpeg.RENDER_REPORT)
    assert report["music"].endswith("bed.wav")
    assert report["captions"]["pages"] == 0
    final_cmd = next(c for c in report["commands"] if str(final) in c)
    fc = final_cmd[final_cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" in fc
    assert "overlay" not in fc


def test_video_cuts_follow_absolute_timeline(tmp_path):
    """align.py's fallback timing legitimately has leading silence and
    inter-scene gaps; the video cut must tile [0, total] from absolute scene
    starts, or visuals drift away from the narration/caption timeline."""
    proj = _make_project(tmp_path, with_captions=False)
    cap_dir = proj.dir / render_ffmpeg.CAPTIONS_DIR
    cap_dir.mkdir()
    (cap_dir / render_ffmpeg.CAPTIONS_MANIFEST).write_text(
        '{"band": null, "entries": []}', encoding="utf-8")
    proj.write_json(contract.TIMING, {
        "total_seconds": TOTAL,
        "scenes": [
            {"id": 1, "start": 0.5, "end": 2.0, "words": []},  # leading silence
            {"id": 2, "start": 2.2, "end": 4.0, "words": []},  # 0.2s gap
        ],
    })
    render_ffmpeg.run(proj, _cfg(str(tmp_path / "no_music")), {})

    report = proj.read_json(render_ffmpeg.RENDER_REPORT)
    durs = [row["duration"] for row in report["scenes"]]
    # scene 1 covers [0, 2.2) (absorbing the lead-in), scene 2 [2.2, 4.0]
    assert durs == [pytest.approx(2.2), pytest.approx(1.8)]
    assert sum(durs) == pytest.approx(TOTAL)

    data = _probe(proj.path(contract.FINAL))
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert float(video["duration"]) == pytest.approx(TOTAL, abs=0.15)


# --------------------------------------------------------------------------
# Unit pieces (no ffmpeg)
# --------------------------------------------------------------------------

def test_cut_frame_counts_tile_the_absolute_timeline():
    scenes = [{"start": 0.0}, {"start": 2.0}]
    assert render_ffmpeg._cut_frame_counts(scenes, 4.0, 15) == [30, 30]
    # leading silence + gap: cuts at 0, next start, total
    gapped = [{"start": 1.0}, {"start": 6.0}]
    assert render_ffmpeg._cut_frame_counts(gapped, 10.0, 30) == [180, 120]


def test_cut_frame_counts_quantize_cumulatively():
    """Per-scene rounding must not accumulate: total frames == round(total*fps)
    even when no scene duration is a multiple of 1/fps."""
    scenes = [{"start": 0.0}, {"start": 1.03}, {"start": 2.06}]
    counts = render_ffmpeg._cut_frame_counts(scenes, 3.09, 30)
    assert sum(counts) == round(3.09 * 30)
    assert all(c >= 1 for c in counts)


def test_cut_frame_counts_degenerate_scene_gets_one_frame():
    scenes = [{"start": 0.0}, {"start": 0.0}]  # zero-length first segment
    counts = render_ffmpeg._cut_frame_counts(scenes, 1.0, 15)
    assert all(c >= 1 for c in counts)


def test_caption_segments_fill_gaps_continuously():
    a, b = Path("a.png"), Path("b.png")
    segs = render_ffmpeg._caption_segments(
        [(a, 0.2, 1.0), (b, 2.5, 3.4)], TOTAL)
    assert [p for p, _ in segs] == [None, a, None, b, None]
    assert [d for _, d in segs] == pytest.approx([0.2, 0.8, 1.5, 0.9, 0.6])
    assert sum(d for _, d in segs) == pytest.approx(TOTAL)


def test_caption_list_repeats_last_entry(tmp_path):
    gap = tmp_path / "_gap.png"
    a = tmp_path / "a.png"
    lst = tmp_path / "list.txt"
    render_ffmpeg._write_caption_list([(a, 1.5), (None, 2.5)], gap, lst)
    lines = lst.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ffconcat version 1.0"
    assert lines[1] == f"file '{a.as_posix()}'"
    assert lines[2] == "duration 1.500000"
    assert lines[3] == f"file '{gap.as_posix()}'"
    assert lines[4] == "duration 2.500000"
    assert lines[5] == f"file '{gap.as_posix()}'"  # repeated, no duration


def test_pick_music_first_alphabetical(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    for name in ("b_bed.mp3", "a_bed.wav", "c_bed.m4a", "notes.txt"):
        (music / name).write_bytes(b"x")
    cfg = _cfg(str(music))
    assert render_ffmpeg._pick_music(cfg).name == "a_bed.wav"
    assert render_ffmpeg._pick_music(_cfg(str(tmp_path / "nope"))) is None


def test_audio_filter_with_and_without_music():
    acfg = _cfg("unused")["audio"]
    with_music = render_ffmpeg._audio_filter(2, 3, TOTAL, acfg)
    assert "[2:a]asplit=2" in with_music
    assert "[3:a]aloop=loop=-1" in with_music
    assert "atrim=duration=4.000,volume=-14dB" in with_music
    assert "sidechaincompress=threshold=0.05:ratio=8" in with_music
    assert "amix=inputs=2:duration=first" in with_music
    assert "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]" in with_music
    voice_only = render_ffmpeg._audio_filter(2, None, TOTAL, acfg)
    assert "amix" not in voice_only
    assert voice_only.startswith("[2:a]loudnorm=I=-16")


def test_audio_filter_has_entrance_swell_by_default():
    acfg = _cfg("unused")["audio"]  # no entrance keys -> defaults apply
    fc = render_ffmpeg._audio_filter(2, 3, TOTAL, acfg)
    # the ducked bed is faded in and lifted for the opening, then settles
    assert "sidechaincompress" in fc and "[duck]" in fc
    assert "afade=t=in:st=0:d=0.800" in fc
    assert "volume=volume='if(lt(t," in fc and ":eval=frame" in fc
    assert "[bedf]amix=inputs=2:duration=first" in fc


def test_entrance_chain_can_be_disabled():
    assert render_ffmpeg._entrance_chain({"entrance_seconds": 0}) == "anull"
    # louder gain -> larger linear multiplier in the expression
    hot = render_ffmpeg._entrance_chain({"entrance_gain_db": 12, "entrance_seconds": 2})
    assert "afade=t=in" in hot and "eval=frame" in hot


def test_audio_filter_gentle_duck_and_outro_fade():
    fc = render_ffmpeg._audio_filter(2, 3, TOTAL, _cfg("unused")["audio"])
    # sidechain carries attack/release/soft-knee (not a bare gate)
    assert ":attack=15:release=400:makeup=1:knee=6" in fc
    # music fades out at the end so it never hard-cuts (TOTAL=4, outro 2.0)
    assert "afade=t=out:st=2.000:d=2.000[bedf]" in fc


def test_apply_video_fades_adds_in_and_matched_out():
    parts = []
    lbl = render_ffmpeg._apply_video_fades(parts, "[vcat]", 10.0, {},
                                           {"outro_fade": 2.0})
    assert lbl == "[vfinal]"
    joined = ";".join(parts)
    assert "[vcat]fade=t=in:st=0:d=0.500" in joined
    assert "fade=t=out:st=8.000:d=2.000[vfinal]" in joined


def test_apply_video_fades_can_disable():
    parts = []
    lbl = render_ffmpeg._apply_video_fades(
        parts, "[vcat]", 10.0, {"video": {"fade_in": 0, "fade_out": 0}}, {})
    assert lbl == "[vcat]" and parts == []


def test_apply_video_grade_default_chain():
    parts = []
    lbl = render_ffmpeg._apply_video_grade(parts, "[vcat]", {})
    assert lbl == "[vgraded]"
    joined = ";".join(parts)
    for f in ("eq=contrast=1.06", "colortemperature=temperature=5500:mix=0.25",
              "vignette=PI/6"):
        assert f in joined
    assert "noise=" not in joined              # grain off by default (bitrate)


def test_apply_video_grade_grain_opt_in():
    parts = []
    render_ffmpeg._apply_video_grade(parts, "[vcat]", {"video": {"grade": {"grain": 4}}})
    assert "noise=c0_strength=4:c0_flags=t" in ";".join(parts)


def test_apply_video_grade_can_disable():
    parts = []
    lbl = render_ffmpeg._apply_video_grade(parts, "[vcat]", {"video": {"grade": False}})
    assert lbl == "[vcat]" and parts == []


def test_missing_manifest_is_contract_error(tmp_path):
    proj = Project(dir=tmp_path / "p")
    proj.dir.mkdir()
    proj.write_json(contract.SCRIPT, SCRIPT)
    proj.write_json(contract.TIMING, TIMING)
    proj.path(contract.VOICEOVER).write_bytes(b"\0")  # never decoded
    with pytest.raises(ContractError, match="manifest"):
        render_ffmpeg.run(proj, _cfg(str(tmp_path / "no_music")), {})
