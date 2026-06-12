"""Cross-stage integration: the captions stage's output feeds the render
stage's input through captions/manifest.json.

The unit suites for captions and render each exercise their own side of the
manifest with shapes they wrote themselves; this test runs the REAL captions
stage and then the REAL render stage on one project, locking the file
contract between them (manifest key names "frames"/"band_height"/"y",
project-relative png paths, band geometry flowing into the overlay filter).

Real Pillow+raqm and real ffmpeg on tiny inputs (320x568@15fps, 4 seconds);
no network. Arabic literals live in this UTF-8 .py file only (CLAUDE.md
rule 4).
"""

from __future__ import annotations

import json
import subprocess

import pytest

from pipeline import captions, contract, render_ffmpeg
from pipeline.contract import Project

FFMPEG = contract.ffmpeg_path("ffmpeg")
W, H, FPS = 320, 568, 15
TOTAL = 4.0

AR_SCENE_1 = "مرحبا بكم"    # 2 words
AR_SCENE_2 = "إلى اللقاء"   # 2 words

SCRIPT = {
    "meta": {"source_url": "https://example.com/v", "audience": "general Arab",
             "dialect": "MSA", "target_seconds": 4},
    "hook": "خطاف تجريبي",
    "scenes": [
        {"id": 1, "narration_ar": AR_SCENE_1,
         "keywords": [["city night"]], "mood": "calm", "target_seconds": 2},
        {"id": 2, "narration_ar": AR_SCENE_2,
         "keywords": [["desert road"]], "mood": "calm", "target_seconds": 2},
    ],
    "post": {"title": "t", "description": "d", "hashtags": []},
}

TIMING = {
    "total_seconds": TOTAL,
    "scenes": [
        {"id": 1, "start": 0.0, "end": 2.0, "words": [
            {"word": AR_SCENE_1.split()[0], "start": 0.0, "end": 0.8},
            {"word": AR_SCENE_1.split()[1], "start": 0.9, "end": 1.8},
        ]},
        {"id": 2, "start": 2.2, "end": 4.0, "words": [
            {"word": AR_SCENE_2.split()[0], "start": 2.2, "end": 2.9},
            {"word": AR_SCENE_2.split()[1], "start": 3.0, "end": 4.0},
        ]},
    ],
}

N_WORDS = 4


def _cfg(music_dir: str) -> dict:
    return {
        "video": {"width": W, "height": H, "fps": FPS},
        "audio": {"music_dir": music_dir, "music_gain_db": -14,
                  "duck_threshold": 0.05, "duck_ratio": 8,
                  "loudness_lufs": -16},
        "captions": {
            "font": "Tajawal",
            "font_size": 24,
            "primary_color": "&H00FFFFFF",
            "highlight_color": "&H0000D7FF",
            "outline_color": "&H00000000",
            "outline": 1,
            "margin_v": 48,
            "karaoke": True,
        },
    }


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory):
    """captions.run() then render_ffmpeg.run() on the same project."""
    root = tmp_path_factory.mktemp("integration")
    proj = Project(dir=root / "p")
    proj.dir.mkdir(parents=True)
    proj.write_json(contract.SCRIPT, SCRIPT)
    proj.write_json(contract.TIMING, TIMING)
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

    cfg = _cfg(str(root / "no_music_dir"))  # missing dir -> voice only
    captions.run(proj, cfg, {})
    render_ffmpeg.run(proj, cfg, {})

    manifest = json.loads(
        (proj.dir / captions.CAPTIONS_DIR / captions.MANIFEST)
        .read_text(encoding="utf-8"))
    return proj, cfg, manifest


def test_render_parses_the_manifest_captions_actually_writes(pipeline_run):
    """_load_manifest must accept captions.py's real on-disk shape."""
    proj, cfg, manifest = pipeline_run
    # sanity: this is the captions-stage shape, not a hand-rolled one
    assert manifest["frames"] and "band_height" in manifest

    entries, band = render_ffmpeg._load_manifest(proj, H, cfg)
    assert len(entries) == len(manifest["frames"]) == N_WORDS
    assert band["y"] == manifest["y"]
    assert band["height"] == manifest["band_height"]
    assert band["width"] == manifest["width"] == W
    for png, start, end in entries:
        assert png.exists()
        assert start < end


def test_final_video_renders_with_caption_overlay(pipeline_run):
    proj, _, manifest = pipeline_run
    final = proj.path(contract.FINAL)
    assert final.exists()

    proc = subprocess.run(
        [contract.ffmpeg_path("ffprobe"), "-v", "error", "-print_format",
         "json", "-show_format", "-show_streams", str(final)],
        check=True, capture_output=True, text=True, encoding="utf-8")
    data = json.loads(proc.stdout)
    assert abs(float(data["format"]["duration"]) - TOTAL) <= 0.5
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (W, H)

    report = proj.read_json(render_ffmpeg.RENDER_REPORT)
    assert report["captions"]["pages"] == N_WORDS  # all frames overlaid
    final_cmd = next(c for c in report["commands"] if str(final) in c)
    fc = final_cmd[final_cmd.index("-filter_complex") + 1]
    assert f"overlay=x=0:y={manifest['y']}:" in fc  # captions geometry won
