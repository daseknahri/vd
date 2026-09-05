# -*- coding: utf-8 -*-
"""Generated-B-roll provider (ComfyUI SDXL+LoRA still -> ffmpeg Ken Burns pan)
and its footage-stage integration. ComfyUI and ffmpeg are fully mocked — no
GPU, no network, no models, no subprocess execution."""

import pytest

from pipeline import broll_image, contract, footage
from pipeline.errors import StageError


# -- prompt building -----------------------------------------------------------
def test_prompt_for_scene_uses_broll_prompt_verbatim_with_lora_trigger():
    p = broll_image.prompt_for_scene(
        {"broll_prompt": "a fox reading a book by candlelight"})
    assert p.startswith(broll_image.LORA_TRIGGER + ",")
    assert "a fox reading a book by candlelight" in p


def test_prompt_for_scene_strips_style_lead_in_and_appends_suffix():
    # the video-script skill writes "STYLE LEAD-IN — CONTENT"; the lead-in must
    # be dropped so it doesn't fight the engine's configured style.
    p = broll_image.prompt_for_scene(
        {"broll_prompt": "watercolor storybook style, muted palette — a fox in a snowy forest"})
    assert "watercolor storybook style" not in p
    assert "a fox in a snowy forest" in p
    assert broll_image.DEFAULT_STYLE_SUFFIX in p


def test_prompt_for_scene_falls_back_to_keywords_and_style_suffix():
    p = broll_image.prompt_for_scene(
        {"keywords": [["desert dunes at sunset"]], "mood": "calm"})
    assert broll_image.LORA_TRIGGER in p
    assert "desert dunes at sunset" in p
    assert broll_image.DEFAULT_STYLE_SUFFIX in p


# -- build / config ------------------------------------------------------------
def test_build_defaults():
    g = broll_image.build({})
    assert g.checkpoint == "sd_xl_base_1.0.safetensors"
    assert "StoryBookRedmond" in g.lora
    assert g.steps == 26
    assert g.cfg == 6.0
    assert g.width == 768 and g.height == 1344
    assert g.out_width == 1080 and g.out_height == 1920


def test_build_overrides():
    g = broll_image.build({"broll": {
        "image": {"checkpoint": "ck.safetensors", "lora": "custom_lora.safetensors",
                  "steps": 20, "cfg": 5.0, "width": 512, "height": 896},
        "out_width": 720, "out_height": 1280,
    }})
    assert g.checkpoint == "ck.safetensors"
    assert g.lora == "custom_lora.safetensors"
    assert g.steps == 20 and g.cfg == 5.0
    assert g.width == 512 and g.height == 896
    assert g.out_width == 720 and g.out_height == 1280


# -- workflow graph ------------------------------------------------------------
def test_workflow_wires_checkpoint_lora_vae_prompt_seed_and_sampler():
    g = broll_image.build({"broll": {"image": {
        "checkpoint": "ck.safetensors", "lora": "lora.safetensors",
        "vae": "vae.safetensors"}}})
    wf = g._workflow("a fox in a forest, KidsRedmAF", seed=42)

    assert wf["1"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["1"]["inputs"]["ckpt_name"] == "ck.safetensors"

    assert wf["2"]["class_type"] == "LoraLoader"
    assert wf["2"]["inputs"]["lora_name"] == "lora.safetensors"
    assert wf["2"]["inputs"]["model"] == ["1", 0]
    assert wf["2"]["inputs"]["clip"] == ["1", 1]

    assert wf["3"]["class_type"] == "VAELoader"
    assert wf["3"]["inputs"]["vae_name"] == "vae.safetensors"

    assert wf["4"]["class_type"] == "CLIPTextEncode"
    assert wf["4"]["inputs"]["text"] == "a fox in a forest, KidsRedmAF"
    assert wf["4"]["inputs"]["clip"] == ["2", 1]

    assert wf["6"]["class_type"] == "EmptyLatentImage"
    assert wf["6"]["inputs"]["width"] == g.width
    assert wf["6"]["inputs"]["height"] == g.height

    assert wf["7"]["class_type"] == "KSampler"
    assert wf["7"]["inputs"]["seed"] == 42
    assert wf["7"]["inputs"]["steps"] == g.steps
    assert wf["7"]["inputs"]["cfg"] == g.cfg
    assert wf["7"]["inputs"]["sampler_name"] == g.sampler
    assert wf["7"]["inputs"]["scheduler"] == g.scheduler

    assert wf["9"]["class_type"] == "SaveImage"


# -- generate() with ComfyUI + ffmpeg mocked -----------------------------------
class _Resp:
    def __init__(self, *, js=None, content=b""):
        self._js, self.content = js, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._js


def _mock(monkeypatch, *, history, post_js=None):
    post_js = post_js if post_js is not None else {"prompt_id": "p1", "node_errors": {}}
    monkeypatch.setattr(broll_image.requests, "post",
                        lambda url, json=None, timeout=None: _Resp(js=post_js))

    def fake_get(url, timeout=None):
        if "/history/" in url:
            return _Resp(js=history)
        if "/view" in url:
            return _Resp(content=b"PNGBYTES")
        return _Resp(js={})
    monkeypatch.setattr(broll_image.requests, "get", fake_get)


def test_generate_writes_out_mp4_and_passes_png_and_duration(monkeypatch, tmp_path):
    g = broll_image.build({})
    monkeypatch.setattr(g, "_generate_still", lambda prompt, seed: b"PNGBYTES")
    captured = {}

    def fake_ken_burns(png, out_mp4, dur, fps, w, h, seed):
        captured.update(png=png, out_mp4=out_mp4, dur=dur, fps=fps, w=w, h=h, seed=seed)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"MP4")
    monkeypatch.setattr(broll_image, "_ken_burns", fake_ken_burns)

    out = tmp_path / "scene_001.mp4"
    g.generate("a prompt", out, seed=7, duration=5.0)

    assert out.read_bytes() == b"MP4"
    assert captured["png"] == b"PNGBYTES"
    assert captured["dur"] == 5.0
    assert captured["seed"] == 7
    assert captured["fps"] == g.fps
    assert captured["w"] == g.out_width and captured["h"] == g.out_height


def test_generate_clamps_duration_to_max_seconds_and_floors_at_one(monkeypatch, tmp_path):
    g = broll_image.build({"broll": {"max_seconds": 8.0}})
    monkeypatch.setattr(g, "_generate_still", lambda prompt, seed: b"PNGBYTES")
    captured = {}

    def fake_ken_burns(png, out_mp4, dur, fps, w, h, seed):
        captured["dur"] = dur
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"MP4")
    monkeypatch.setattr(broll_image, "_ken_burns", fake_ken_burns)

    g.generate("p", tmp_path / "s1.mp4", seed=1, duration=99.0)
    assert captured["dur"] == 8.0
    g.generate("p", tmp_path / "s2.mp4", seed=1, duration=0.01)
    assert captured["dur"] == 1.0


def test_generate_success_via_full_comfy_mock(monkeypatch, tmp_path):
    history = {"p1": {"status": {"status_str": "success"}, "outputs": {
        "9": {"images": [{"filename": "vf_img_00001_.png",
                          "subfolder": "", "type": "output"}]}}}}
    _mock(monkeypatch, history=history)
    captured = {}

    def fake_ken_burns(png, out_mp4, dur, fps, w, h, seed):
        captured["png"] = png
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"MP4")
    monkeypatch.setattr(broll_image, "_ken_burns", fake_ken_burns)

    out = tmp_path / "scene_001.mp4"
    broll_image.build({}).generate("a forest", out, seed=1, duration=5.0)
    assert out.read_bytes() == b"MP4"
    assert captured["png"] == b"PNGBYTES"


def test_generate_node_errors_raise(monkeypatch, tmp_path):
    _mock(monkeypatch, history={}, post_js={"prompt_id": "p1", "node_errors": {"4": "bad input"}})
    with pytest.raises(StageError, match="rejected"):
        broll_image.build({}).generate("x", tmp_path / "s.mp4", seed=1, duration=5.0)


def test_generate_no_image_output_raises(monkeypatch, tmp_path):
    _mock(monkeypatch, history={"p1": {"status": {"status_str": "success"}, "outputs": {}}})
    with pytest.raises(StageError, match="no image output"):
        broll_image.build({}).generate("x", tmp_path / "s.mp4", seed=1, duration=5.0)


def test_generate_connection_error_raises(monkeypatch, tmp_path):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(broll_image.requests, "post", boom)
    with pytest.raises(StageError, match="not reachable"):
        broll_image.build({}).generate("x", tmp_path / "s.mp4", seed=1, duration=5.0)


# -- flat-white border trim ----------------------------------------------------
def _png(img):
    from io import BytesIO
    b = BytesIO(); img.save(b, format="PNG"); return b.getvalue()


def test_trim_flat_border_removes_pure_white_edge_band():
    from io import BytesIO
    from PIL import Image
    img = Image.new("RGB", (200, 400), (120, 120, 120))  # flat gray content
    for x in range(180, 200):                              # 10% pure-white right band
        for y in range(400):
            img.putpixel((x, y), (255, 255, 255))
    out = broll_image._trim_flat_border(_png(img))
    w, h = Image.open(BytesIO(out)).size
    assert w == 180 and h == 400          # exactly the white band removed
    assert out != _png(img)


def test_trim_flat_border_leaves_full_bleed_untouched():
    from PIL import Image
    img = Image.new("RGB", (200, 400), (120, 120, 120))   # no pure-white edge
    src = _png(img)
    assert broll_image._trim_flat_border(src) == src      # unchanged bytes


def test_trim_flat_border_ignores_pale_but_not_pure_edges():
    # a pale sky/snow edge (near white but < threshold, or textured) must survive
    from PIL import Image
    img = Image.new("RGB", (200, 400), (245, 245, 245))   # pale, but < white=252
    src = _png(img)
    assert broll_image._trim_flat_border(src) == src


# -- footage.run integration (ai_broll, engine="image") -------------------------
def _script(scenes):
    return {"meta": {"source_url": "https://example.com/v", "audience": "general Arab",
                     "dialect": "MSA", "target_seconds": 90},
            "hook": "لماذا؟", "scenes": scenes,
            "post": {"title": "", "description": "", "hashtags": []}}


def _scene(sid):
    return {"id": sid, "narration_ar": "نص عربي قصير.",
            "keywords": [["desert dunes at sunset"]], "mood": "calm", "target_seconds": 8,
            "broll_prompt": "a fox reading a book by candlelight"}


def _cfg():
    return {"video": {"aspect_ratio": "9:16"},
            "footage": {"ai_broll": True, "providers": ["pexels"],
                       "broll": {"engine": "image"}}}


def test_footage_run_ai_broll_image_engine_generates_clips(monkeypatch, tmp_path):
    project = contract.Project(dir=tmp_path)
    project.write_json(contract.SCRIPT, _script([_scene(1), _scene(2)]))
    project.write_json(contract.TIMING, {"total_seconds": 9.0, "scenes": [
        {"id": 1, "start": 0.0, "end": 3.0, "words": [{"word": "x", "start": 0.0, "end": 3.0}]},
        {"id": 2, "start": 3.0, "end": 9.0, "words": [{"word": "y", "start": 3.0, "end": 9.0}]},
    ]})

    calls = []

    class FakeGen:
        def generate(self, prompt, out, seed, duration=None):
            calls.append((prompt, out, seed, duration))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"MP4")

    monkeypatch.setattr(broll_image, "build", lambda fcfg: FakeGen())
    footage.run(project, _cfg(), {})   # env empty: broll mode needs no API keys

    assert (tmp_path / "clips" / "scene_001.mp4").read_bytes() == b"MP4"
    assert (tmp_path / "clips" / "scene_002.mp4").read_bytes() == b"MP4"

    report = project.read_json(contract.FOOTAGE_REPORT)
    assert [e["status"] for e in report] == ["generated", "generated"]
    assert [e["provider"] for e in report] == ["comfyui-sdxl", "comfyui-sdxl"]
    assert len(calls) == 2

    # per-scene duration came from timing.json (end - start), not target_seconds
    by_name = {out.name: dur for _, out, _, dur in calls}
    assert by_name["scene_001.mp4"] == 3.0
    assert by_name["scene_002.mp4"] == 6.0
