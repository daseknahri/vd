"""Tests for pipeline/captions.py — real Pillow+raqm renders on tiny canvases.

Arabic literals live in this UTF-8 .py file only (never in command strings,
CLAUDE.md rule 4). No network, no ffmpeg needed: captions is pure Pillow.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image, features

from pipeline import captions, contract
from pipeline.contract import ContractError, Project

AR_SCENE_1 = "العلم نور والجهل ظلام"                 # 4 words
AR_SCENE_2 = "التاريخ يعيد نفسه دائما في كل زمان"     # 7 words
AR_SCENE_3 = "هذه الكلمات الخمس بدون توقيت"           # 5 words; timing has 3

WORD_COUNT = 4 + 7 + 5

VIDEO_W, VIDEO_H = 720, 1280
MARGIN_V = 96
HIGHLIGHT_RGB = (255, 215, 0)   # &H0000D7FF -> amber
PRIMARY_RGB = (255, 255, 255)


def make_cfg(**captions_overrides):
    cfg = {
        "video": {"width": VIDEO_W, "height": VIDEO_H},
        "captions": {
            "font": "Tajawal",
            "font_size": 36,
            "primary_color": "&H00FFFFFF",
            "highlight_color": "&H0000D7FF",
            "outline_color": "&H00000000",
            "outline": 1,
            "margin_v": MARGIN_V,
            "karaoke": True,
        },
    }
    cfg["captions"].update(captions_overrides)
    return cfg


def make_script():
    def scene(i, narration):
        return {
            "id": i,
            "narration_ar": narration,
            "keywords": [["library books"], ["old manuscripts"]],
            "mood": "calm",
            "target_seconds": 5,
        }

    return {
        "meta": {
            "source_url": "https://example.com/v",
            "audience": "general Arab",
            "dialect": "MSA",
            "target_seconds": 30,
        },
        "hook": "افتتاحية قصيرة",
        "scenes": [
            scene(1, AR_SCENE_1),
            scene(2, AR_SCENE_2),
            scene(3, AR_SCENE_3),
        ],
        "post": {"title": "عنوان", "description": "وصف", "hashtags": ["تاريخ"]},
    }


def make_timing():
    def words(triples):
        return [{"word": w, "start": s, "end": e} for w, s, e in triples]

    s1, s2, s3 = AR_SCENE_1.split(), AR_SCENE_2.split(), AR_SCENE_3.split()
    return {
        "total_seconds": 9.5,
        "scenes": [
            # deliberate 0.1s gaps between words: manifest must absorb them
            {"id": 1, "start": 0.0, "end": 2.0, "words": words([
                (s1[0], 0.0, 0.4), (s1[1], 0.5, 0.9),
                (s1[2], 1.0, 1.4), (s1[3], 1.5, 2.0),
            ])},
            {"id": 2, "start": 2.5, "end": 6.0, "words": words([
                (s2[i], 2.5 + 0.5 * i,
                 2.5 + 0.5 * i + (0.45 if i < 6 else 0.5))
                for i in range(7)
            ])},
            # 3 timing words vs 5 narration words -> proportional fallback
            {"id": 3, "start": 6.5, "end": 9.5, "words": words([
                (s3[0], 6.5, 7.4), (s3[1], 7.5, 8.4), (s3[2], 8.5, 9.5),
            ])},
        ],
    }


def new_project(tmp_path) -> Project:
    proj = Project(dir=tmp_path)
    proj.write_json(contract.SCRIPT, make_script())
    proj.write_json(contract.TIMING, make_timing())
    return proj


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """One real Tajawal render shared by the read-only tests."""
    proj = new_project(tmp_path_factory.mktemp("proj"))
    captions.run(proj, make_cfg(), {})
    manifest = json.loads(
        (proj.path(captions.CAPTIONS_DIR) / captions.MANIFEST)
        .read_text(encoding="utf-8")
    )
    return proj, manifest


def load_frame(proj, frame) -> Image.Image:
    return Image.open(proj.dir / frame["png"])


def color_bbox(img, rgb):
    """Bounding box of pixels exactly matching rgb at full alpha, else None."""
    w = img.width
    px = img.load()
    xs, ys = [], []
    for y in range(img.height):
        for x in range(w):
            p = px[x, y]
            if p[3] == 255 and p[:3] == rgb:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def boxes_overlap(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# --------------------------------------------------------------------------
# Environment + pure helpers
# --------------------------------------------------------------------------

def test_raqm_is_available():
    assert features.check("raqm"), "Pillow must be built with libraqm"


def test_ass_color_parsing():
    assert captions.ass_color("&H00FFFFFF") == (255, 255, 255, 255)
    assert captions.ass_color("&H0000D7FF") == (255, 215, 0, 255)
    assert captions.ass_color("&H00000000") == (0, 0, 0, 255)
    assert captions.ass_color("&H80112233&") == (0x33, 0x22, 0x11, 127)
    assert captions.ass_color("FFFFFF") == (255, 255, 255, 255)
    for bad in ("&H", "", "&HZZZZZZZZ", "&H123456789"):
        with pytest.raises(ContractError):
            captions.ass_color(bad)


def test_font_resolution_prefers_bold():
    path = captions._font_file(captions.FONTS_DIR, "Tajawal")
    assert path.name == "Tajawal-Bold.ttf"
    assert captions._font_file(captions.FONTS_DIR, "tajawal").name == "Tajawal-Bold.ttf"
    assert captions._font_file(captions.FONTS_DIR, "Cairo").name == "Cairo-Variable.ttf"
    with pytest.raises(ContractError):
        captions._font_file(captions.FONTS_DIR, "NoSuchFamily")


# --------------------------------------------------------------------------
# Outputs + manifest contract
# --------------------------------------------------------------------------

def test_outputs_and_counts(rendered):
    proj, manifest = rendered
    pngs = sorted((proj.path(captions.CAPTIONS_DIR)).glob("cap_*.png"))
    assert len(pngs) == WORD_COUNT
    assert len(manifest["frames"]) == WORD_COUNT
    assert proj.path(contract.CAPTIONS).exists()
    assert proj.path(captions.REPORT).exists()
    # frames reference existing files, in numbering order
    for i, frame in enumerate(manifest["frames"], start=1):
        assert frame["png"] == f"captions/cap_{i:04d}.png"
        assert (proj.dir / frame["png"]).exists()


def test_manifest_band_geometry(rendered):
    _, manifest = rendered
    assert manifest["width"] == VIDEO_W
    assert manifest["band_height"] > 0
    assert manifest["y"] == VIDEO_H - manifest["band_height"] - MARGIN_V
    assert 0 < manifest["y"] < VIDEO_H


def test_manifest_monotonic_and_gapless_within_pages(rendered):
    _, manifest = rendered
    frames = manifest["frames"]
    starts = [f["start"] for f in frames]
    assert starts == sorted(starts)
    for f in frames:
        assert f["start"] < f["end"]
    by_page: dict[int, list[dict]] = {}
    for f in frames:
        by_page.setdefault(f["page"], []).append(f)
    for page_frames in by_page.values():
        for a, b in zip(page_frames, page_frames[1:]):
            assert a["end"] == b["start"], "gap inside a page -> caption flicker"


def test_word_intervals_follow_timing(rendered):
    """Scene 1 words start at their timed starts; each frame holds until the
    next word starts (gap absorbed); page-final frame ends at page end."""
    _, manifest = rendered
    scene1 = manifest["frames"][:4]
    assert [f["start"] for f in scene1] == [0.0, 0.5, 1.0, 1.5]
    for a, b in zip(scene1, scene1[1:]):
        if a["page"] == b["page"]:
            assert a["end"] == b["start"]
    last = scene1[-1]
    assert last["end"] == 2.0  # scene/page end, not the word's own 2.0-gap end


def test_pngs_are_rgba_with_alpha(rendered):
    proj, manifest = rendered
    for frame in manifest["frames"]:
        with load_frame(proj, frame) as img:
            assert img.mode == "RGBA"
            assert img.height == manifest["band_height"]
            assert img.width == manifest["width"]
            assert img.getchannel("A").getextrema()[1] > 0, "blank caption frame"


# --------------------------------------------------------------------------
# Karaoke highlight — pixel-level verification of the real Tajawal render
# --------------------------------------------------------------------------

def test_highlight_hits_exactly_one_word_region_per_frame(rendered):
    proj, manifest = rendered
    by_page: dict[int, list[dict]] = {}
    for f in manifest["frames"]:
        by_page.setdefault(f["page"], []).append(f)
    for page_frames in by_page.values():
        boxes = []
        for frame in page_frames:
            with load_frame(proj, frame) as img:
                box = color_bbox(img, HIGHLIGHT_RGB)
                assert box is not None, f"no highlight pixels in {frame['png']}"
                if len(page_frames) > 1:
                    assert color_bbox(img, PRIMARY_RGB) is not None, (
                        "inactive words must stay in the primary color"
                    )
                boxes.append(box)
        # Each frame highlights a different word, so the highlight regions of
        # a page's frames must be pairwise disjoint. A frame that colored two
        # words (or the wrong one) would produce an overlapping region.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                assert not boxes_overlap(boxes[i], boxes[j]), (
                    f"highlight regions of frames {i} and {j} overlap"
                )


# --------------------------------------------------------------------------
# Word-count mismatch -> proportional timing + report warning
# --------------------------------------------------------------------------

def test_mismatch_distributes_proportionally_and_warns(rendered):
    proj, manifest = rendered
    scene3_words = AR_SCENE_3.split()
    scene3 = manifest["frames"][-len(scene3_words):]
    start, end = 6.5, 9.5
    total = sum(len(w) for w in scene3_words)
    acc = 0
    for frame, word in zip(scene3, scene3_words):
        assert frame["start"] == pytest.approx(
            start + (end - start) * acc / total, abs=2e-3)
        acc += len(word)
    assert scene3[0]["start"] == pytest.approx(start, abs=2e-3)
    assert scene3[-1]["end"] == pytest.approx(end, abs=2e-3)

    report = proj.read_json(captions.REPORT)
    mismatch = [w for w in report["warnings"] if w.get("scene") == 3]
    assert mismatch, "missing word-count-mismatch warning for scene 3"
    assert mismatch[0]["narration_words"] == 5
    assert mismatch[0]["timing_words"] == 3


# --------------------------------------------------------------------------
# captions.ass export artifact
# --------------------------------------------------------------------------

def test_ass_export_is_portable_artifact(rendered):
    proj, manifest = rendered
    text = proj.path(contract.CAPTIONS).read_text(encoding="utf-8-sig")
    assert "[Script Info]" in text
    assert "[V4+ Styles]" in text
    assert "[Events]" in text
    assert f"PlayResX: {VIDEO_W}" in text
    assert "Tajawal" in text
    assert "&H00FFFFFF" in text and "&H0000D7FF" in text
    assert "NEVER burn" in text  # portability comment, CLAUDE.md rule 3
    n_pages = len({f["page"] for f in manifest["frames"]})
    assert text.count("Dialogue:") == n_pages
    for word in AR_SCENE_1.split() + AR_SCENE_3.split():
        assert word in text
    assert text.splitlines()[-1].startswith("Dialogue:")
    assert "0:00:00.00" in text


# --------------------------------------------------------------------------
# Idempotency / force / failure modes
# --------------------------------------------------------------------------

def test_idempotent_then_force_regenerates(tmp_path):
    proj = new_project(tmp_path)
    cfg = make_cfg()
    captions.run(proj, cfg, {})
    cap_dir = proj.path(captions.CAPTIONS_DIR)
    manifest_path = cap_dir / captions.MANIFEST
    png1 = cap_dir / "cap_0001.png"
    before = (manifest_path.stat().st_mtime_ns, png1.stat().st_mtime_ns)

    captions.run(proj, cfg, {})  # outputs exist -> early return
    assert (manifest_path.stat().st_mtime_ns, png1.stat().st_mtime_ns) == before

    png1.unlink()
    captions.run(proj, cfg, {})  # manifest still present -> still a no-op
    assert not png1.exists()

    captions.run(proj, cfg, {}, force=True)
    assert png1.exists()
    pngs = list(cap_dir.glob("cap_*.png"))
    assert len(pngs) == WORD_COUNT  # stale frames cleared, full set rebuilt


def test_karaoke_off_renders_one_frame_per_page(tmp_path):
    proj = new_project(tmp_path)
    captions.run(proj, make_cfg(karaoke=False), {})
    manifest = json.loads(
        (proj.path(captions.CAPTIONS_DIR) / captions.MANIFEST)
        .read_text(encoding="utf-8")
    )
    frames = manifest["frames"]
    assert len(frames) == len({f["page"] for f in frames})
    assert len(frames) < WORD_COUNT
    for f in frames:
        assert f["start"] < f["end"]


def test_missing_inputs_raise_contract_error(tmp_path):
    proj = Project(dir=tmp_path)
    proj.write_json(contract.SCRIPT, make_script())
    with pytest.raises(ContractError):
        captions.run(proj, make_cfg(), {})


def test_timing_missing_scene_raises_contract_error(tmp_path):
    proj = Project(dir=tmp_path)
    proj.write_json(contract.SCRIPT, make_script())
    timing = make_timing()
    timing["scenes"] = timing["scenes"][:2]  # drop scene 3
    proj.write_json(contract.TIMING, timing)
    with pytest.raises(ContractError):
        captions.run(proj, make_cfg(), {})


def test_unknown_font_raises_contract_error(tmp_path):
    proj = new_project(tmp_path)
    with pytest.raises(ContractError):
        captions.run(proj, make_cfg(font="NoSuchFamily"), {})


def test_crash_during_force_rerun_self_heals(tmp_path, monkeypatch):
    """force=True must invalidate the manifest (the completion marker)
    BEFORE deleting frames: if the forced run dies midway, a plain re-run
    must rebuild instead of no-opping over missing PNGs."""
    proj = new_project(tmp_path)
    cfg = make_cfg()
    captions.run(proj, cfg, {})
    cap_dir = proj.path(captions.CAPTIONS_DIR)
    manifest_path = cap_dir / captions.MANIFEST

    def boom(*a, **k):
        raise RuntimeError("font exploded mid-page")

    monkeypatch.setattr(captions, "_render_frame", boom)
    with pytest.raises(RuntimeError):
        captions.run(proj, cfg, {}, force=True)
    assert not manifest_path.exists()  # stage no longer looks complete

    monkeypatch.undo()
    captions.run(proj, cfg, {})  # plain re-run, no force needed
    assert manifest_path.exists()
    assert len(list(cap_dir.glob("cap_*.png"))) == WORD_COUNT


# --------------------------------------------------------------------------
# Zero-length word spans (align.py fallback) must not poison the manifest
# --------------------------------------------------------------------------

def test_zero_length_word_spans_are_skipped_not_propagated(tmp_path):
    """align.py's interpolation can emit zero-length word spans (matched
    neighbors touching). They are contract-valid, so captions must drop the
    resulting zero-duration frames instead of writing manifest entries the
    render stage would reject."""
    proj = Project(dir=tmp_path)
    proj.write_json(contract.SCRIPT, make_script())
    timing = make_timing()
    words = timing["scenes"][0]["words"]
    # word 2 collapses to a point exactly at word 3's start
    words[1]["start"] = words[1]["end"] = words[2]["start"] = 1.0
    proj.write_json(contract.TIMING, timing)

    captions.run(proj, make_cfg(), {})

    manifest = json.loads(
        (proj.path(captions.CAPTIONS_DIR) / captions.MANIFEST)
        .read_text(encoding="utf-8"))
    assert len(manifest["frames"]) == WORD_COUNT - 1  # one frame dropped
    for f in manifest["frames"]:
        assert f["end"] > f["start"]
        assert (proj.dir / f["png"]).exists()


# --------------------------------------------------------------------------
# Bidi: embedded LTR runs keep left-to-right order inside the RTL line
# --------------------------------------------------------------------------

def _word(text, width):
    return {"text": text, "width": float(width), "start": 0.0, "end": 1.0}


def test_embedded_ltr_run_keeps_visual_order():
    line = [_word("جرب", 50), _word("iPhone", 80), _word("15", 30),
            _word("اليوم", 60)]
    flat = captions._position([line], VIDEO_W, 10.0)
    x = {w["text"]: w["x"] for w in flat}
    # RTL line: first word rightmost, last word leftmost...
    assert x["جرب"] > x["iPhone"] and x["جرب"] > x["15"]
    assert x["اليوم"] < x["iPhone"] and x["اليوم"] < x["15"]
    # ...but the LTR run reads left-to-right WITHIN itself (UAX#9)
    assert x["iPhone"] < x["15"]
    # narration (chronological) order is preserved for karaoke indexing
    assert [w["text"] for w in flat] == ["جرب", "iPhone", "15", "اليوم"]


def test_pure_rtl_line_layout_unchanged():
    line = [_word("العلم", 50), _word("نور", 40), _word("والجهل", 70),
            _word("ظلام", 55)]
    flat = captions._position([line], VIDEO_W, 10.0)
    xs = [w["x"] for w in flat]
    assert xs == sorted(xs, reverse=True)  # strictly right-to-left
    assert flat[0]["x"] == VIDEO_W - captions.H_MARGIN - 50


def test_two_word_latin_run_reads_left_to_right():
    line = [_word("زرت", 45), _word("New", 50), _word("York", 60),
            _word("أمس", 40)]
    flat = captions._position([line], VIDEO_W, 10.0)
    x = {w["text"]: w["x"] for w in flat}
    assert x["New"] < x["York"]            # not reversed
    assert x["York"] < x["زرت"]            # run sits left of the first word
    assert x["أمس"] < x["New"]             # and right of the following word
