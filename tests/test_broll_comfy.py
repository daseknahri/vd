# -*- coding: utf-8 -*-
"""Generated-B-roll provider (ComfyUI + LTX-Video) and its footage-stage
integration. ComfyUI is fully mocked — no GPU, no network, no models."""

import pytest

from pipeline import broll_comfy, contract, footage
from pipeline.errors import StageError


# -- prompt building -----------------------------------------------------------
def test_prompt_for_scene_uses_keywords_and_mood():
    p = broll_comfy.prompt_for_scene(
        {"keywords": [["neon city street", "rain at night"]], "mood": "energetic"})
    assert "neon city street, rain at night" in p
    assert "energetic" in p


def test_prompt_for_scene_handles_empty_keywords():
    p = broll_comfy.prompt_for_scene({"keywords": [], "mood": ""})
    assert isinstance(p, str) and len(p) > 0


def test_prompt_for_scene_prefers_explicit_broll_prompt():
    p = broll_comfy.prompt_for_scene(
        {"keywords": [["ignored"]], "mood": "calm", "broll_prompt": "MY CUSTOM PROMPT"})
    assert p == "MY CUSTOM PROMPT"


# -- build / config ------------------------------------------------------------
def test_build_defaults():
    g = broll_comfy.build({})
    assert g.url == "http://127.0.0.1:8188"
    # default is the 8-step distilled model (cfg 1.0)
    assert "distilled" in g.checkpoint and g.steps == 8 and g.cfg == 1.0


def test_build_overrides_and_strips_trailing_slash():
    g = broll_comfy.build({"broll": {"comfy_url": "http://host:9/", "steps": 8,
                                     "width": 512, "sampler": "dpmpp_2m"}})
    assert g.url == "http://host:9"
    assert g.steps == 8 and g.width == 512 and g.sampler == "dpmpp_2m"


# -- workflow graph ------------------------------------------------------------
def test_workflow_wires_models_prompt_and_seed():
    g = broll_comfy.build({"broll": {"checkpoint": "ck.safetensors", "t5": "t5.safetensors"}})
    wf = g._workflow("a green forest", seed=7, length=97)
    assert wf["1"]["inputs"]["ckpt_name"] == "ck.safetensors"
    assert wf["2"]["inputs"]["clip_name"] == "t5.safetensors"
    assert wf["2"]["inputs"]["type"] == "ltxv"
    assert wf["3"]["inputs"]["text"] == "a green forest"
    assert wf["10"]["inputs"]["noise_seed"] == 7
    assert wf["11"]["inputs"]["samples"] == ["10", 0]   # decode <- sampler
    assert wf["12"]["class_type"] == "SaveWEBM"


# -- generate() with ComfyUI mocked -------------------------------------------
class _Resp:
    def __init__(self, *, js=None, content=b""):
        self._js, self.content = js, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._js


def _mock(monkeypatch, *, history, post_js=None):
    post_js = post_js if post_js is not None else {"prompt_id": "p1", "node_errors": {}}
    monkeypatch.setattr(broll_comfy.requests, "post",
                        lambda url, json=None, timeout=None: _Resp(js=post_js))

    def fake_get(url, timeout=None):
        if "/history/" in url:
            return _Resp(js=history)
        if "/view" in url:
            return _Resp(content=b"WEBMDATA")
        return _Resp(js={})
    monkeypatch.setattr(broll_comfy.requests, "get", fake_get)


def test_generate_writes_mp4(monkeypatch, tmp_path):
    history = {"p1": {"status": {"status_str": "success"}, "outputs": {
        "12": {"images": [{"filename": "vf_broll_00001_.webm",
                           "subfolder": "", "type": "output"}]}}}}
    _mock(monkeypatch, history=history)
    seen = {}
    monkeypatch.setattr(broll_comfy, "_transcode_to_mp4",
                        lambda webm, out: seen.update(webm=webm) or out.write_bytes(b"MP4"))
    out = tmp_path / "scene_001.mp4"
    broll_comfy.build({}).generate("a forest", out, seed=1)
    assert out.read_bytes() == b"MP4"
    assert seen["webm"] == b"WEBMDATA"


def test_generate_node_errors_raise(monkeypatch, tmp_path):
    _mock(monkeypatch, history={}, post_js={"node_errors": {"3": "bad input"}})
    with pytest.raises(StageError, match="rejected"):
        broll_comfy.build({}).generate("x", tmp_path / "s.mp4", seed=1)


def test_generate_no_output_raises(monkeypatch, tmp_path):
    _mock(monkeypatch, history={"p1": {"status": {"status_str": "success"}, "outputs": {}}})
    with pytest.raises(StageError, match="no video output"):
        broll_comfy.build({}).generate("x", tmp_path / "s.mp4", seed=1)


def test_generate_connection_error_raises(monkeypatch, tmp_path):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(broll_comfy.requests, "post", boom)
    with pytest.raises(StageError, match="not reachable"):
        broll_comfy.build({}).generate("x", tmp_path / "s.mp4", seed=1)


# -- footage.run integration (ai_broll) ---------------------------------------
def _script(scenes):
    return {"meta": {"source_url": "https://example.com/v", "audience": "general Arab",
                     "dialect": "MSA", "target_seconds": 90},
            "hook": "لماذا؟", "scenes": scenes,
            "post": {"title": "", "description": "", "hashtags": []}}


def _scene(sid):
    return {"id": sid, "narration_ar": "نص عربي قصير.",
            "keywords": [["desert dunes at sunset"]], "mood": "calm", "target_seconds": 8}


def _cfg():
    return {"video": {"aspect_ratio": "9:16"},
            "footage": {"ai_broll": True, "providers": ["pexels"]}}


def test_footage_run_ai_broll_generates_clips(monkeypatch, tmp_path):
    project = contract.Project(dir=tmp_path)
    project.write_json(contract.SCRIPT, _script([_scene(1), _scene(2)]))

    calls = []

    class FakeGen:
        fps, max_seconds, length = 25, 8.0, 97

        def generate(self, prompt, out, seed, length=None):
            calls.append((prompt, out.name))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"MP4")

    monkeypatch.setattr(broll_comfy, "build", lambda fcfg: FakeGen())
    footage.run(project, _cfg(), {})   # env empty: broll mode needs no keys

    assert (tmp_path / "clips" / "scene_001.mp4").read_bytes() == b"MP4"
    assert (tmp_path / "clips" / "scene_002.mp4").read_bytes() == b"MP4"
    report = project.read_json(contract.FOOTAGE_REPORT)
    assert [e["status"] for e in report] == ["generated", "generated"]
    assert len(calls) == 2


def test_footage_run_ai_broll_records_error_and_continues(monkeypatch, tmp_path):
    project = contract.Project(dir=tmp_path)
    project.write_json(contract.SCRIPT, _script([_scene(1)]))

    class FailGen:
        fps, max_seconds, length = 25, 8.0, 97

        def generate(self, prompt, out, seed, length=None):
            raise StageError("footage", "ComfyUI not reachable at http://x")

    monkeypatch.setattr(broll_comfy, "build", lambda fcfg: FailGen())
    footage.run(project, _cfg(), {})   # must NOT raise

    report = project.read_json(contract.FOOTAGE_REPORT)
    assert report[0]["status"] == "error"
    assert "reachable" in report[0]["error"]
    assert not (tmp_path / "clips" / "scene_001.mp4").exists()


def test_footage_run_ai_broll_raises_when_all_scenes_fail(monkeypatch, tmp_path):
    # One flagged scene continues (test above); a TOTAL wipeout (ComfyUI down/
    # broken) must fail loudly, else the render ships an all-placeholder video.
    project = contract.Project(dir=tmp_path)
    project.write_json(contract.SCRIPT, _script([_scene(1), _scene(2)]))

    class FailGen:
        fps, max_seconds, length = 25, 8.0, 97

        def generate(self, prompt, out, seed, length=None):
            raise StageError("footage", "ComfyUI produced no video output")

    monkeypatch.setattr(broll_comfy, "build", lambda fcfg: FailGen())
    with pytest.raises(StageError, match="failed for ALL 2 scenes"):
        footage.run(project, _cfg(), {})

    # the report is still written (both errors recorded) before the raise
    report = project.read_json(contract.FOOTAGE_REPORT)
    assert [e["status"] for e in report] == ["error", "error"]


# -- per-scene clip length -----------------------------------------------------
def test_frames_for_duration_snaps_up_to_8k_plus_1_and_covers():
    f = broll_comfy.frames_for_duration(6.0, 25, max_seconds=8.0)  # 150 target
    assert (f - 1) % 8 == 0            # valid LTX length
    assert f >= 6.0 * 25               # snapped UP so the clip covers the scene
    assert f == 153                    # ceil((150-1)/8)=19 -> 8*19+1


def test_frames_for_duration_clamps_min_and_max():
    assert broll_comfy.frames_for_duration(0.05, 25) == 25          # min ~1s
    assert broll_comfy.frames_for_duration(60.0, 25, max_seconds=8.0) == 201  # capped at 8s


def test_generate_uses_per_call_length(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(broll_comfy.requests, "post",
                        lambda url, json=None, timeout=None: captured.update(wf=json["prompt"])
                        or _Resp(js={"prompt_id": "p1", "node_errors": {}}))
    hist = {"p1": {"status": {"status_str": "success"}, "outputs": {
        "12": {"images": [{"filename": "x.webm", "subfolder": "", "type": "output"}]}}}}
    monkeypatch.setattr(broll_comfy.requests, "get",
                        lambda url, timeout=None: _Resp(js=hist) if "/history/" in url else _Resp(content=b"W"))
    monkeypatch.setattr(broll_comfy, "_transcode_to_mp4", lambda webm, out: out.write_bytes(b"MP4"))
    broll_comfy.build({}).generate("p", tmp_path / "s.mp4", seed=1, length=57)
    assert captured["wf"]["5"]["inputs"]["length"] == 57   # EmptyLTXVLatentVideo


def test_footage_ai_broll_uses_per_scene_length_from_timing(monkeypatch, tmp_path):
    project = contract.Project(dir=tmp_path)
    project.write_json(contract.SCRIPT, _script([_scene(1), _scene(2)]))
    project.write_json(contract.TIMING, {"total_seconds": 9.0, "scenes": [
        {"id": 1, "start": 0.0, "end": 3.0, "words": [{"word": "x", "start": 0.0, "end": 3.0}]},
        {"id": 2, "start": 3.0, "end": 9.0, "words": [{"word": "y", "start": 3.0, "end": 9.0}]},
    ]})
    seen = {}

    class FakeGen:
        fps, max_seconds, length = 25, 8.0, 97

        def generate(self, prompt, out, seed, length=None):
            seen[out.name] = length
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"MP4")

    monkeypatch.setattr(broll_comfy, "build", lambda fcfg: FakeGen())
    footage.run(project, _cfg(), {})
    # 3s@25 -> ceil((75-1)/8)=10 -> 81 ; 6s@25 -> ceil((150-1)/8)=19 -> 153
    assert seen["scene_001.mp4"] == 81
    assert seen["scene_002.mp4"] == 153
