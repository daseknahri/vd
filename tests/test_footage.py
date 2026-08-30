"""Tests for pipeline/footage.py — all HTTP mocked, zero network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from pipeline import contract, footage
from pipeline.contract import ContractError

ENV = {"PEXELS_API_KEY": "px-key", "PIXABAY_API_KEY": "pb-key"}


# --------------------------------------------------------------------------
# Fixtures / fakes
# --------------------------------------------------------------------------

def make_script(scenes):
    return {
        "meta": {"source_url": "https://example.com/v",
                 "audience": "general Arab", "dialect": "MSA",
                 "target_seconds": 90},
        "hook": "لماذا تختفي الواحات من الصحراء؟",
        "scenes": scenes,
        "post": {"title": "", "description": "", "hashtags": []},
    }


def make_scene(sid, keyword_sets, target_seconds=8):
    return {
        "id": sid,
        "narration_ar": "تمتد الصحراء كبحر من الرمال الذهبية.",
        "keywords": keyword_sets,
        "mood": "calm",
        "target_seconds": target_seconds,
    }


def pexels_video(vid, duration, files):
    """files: list of (width, height, link)."""
    return {
        "id": vid,
        "duration": duration,
        "video_files": [
            {"width": w, "height": h, "link": link, "file_type": "video/mp4"}
            for (w, h, link) in files
        ],
    }


def pixabay_hit(vid, duration, sizes):
    """sizes: {"large"/"medium"/"small": (width, height, url)}."""
    return {
        "id": vid,
        "duration": duration,
        "videos": {name: {"url": url, "width": w, "height": h}
                   for name, (w, h, url) in sizes.items()},
    }


class FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200,
                 headers=None):
        self._json = json_data
        self._content = content
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def close(self):
        pass


class FakeAPI:
    """Stands in for requests.get: search JSON per query, bytes per URL."""

    def __init__(self):
        self.pexels = {}     # query -> videos[]
        self.pixabay = {}    # query -> hits[]
        self.downloads = {}  # url -> bytes
        self.fail_pexels = False
        self.calls = []      # ("pexels"|"pixabay", query) | ("download", url)
        self.last_pexels_headers = None
        self.last_pexels_params = None
        self.last_pixabay_params = None

    def get(self, url, params=None, headers=None, stream=False, timeout=None):
        assert timeout == 30, "every HTTP call must set timeout=30"
        if url.startswith("https://api.pexels.com"):
            self.calls.append(("pexels", params["query"]))
            self.last_pexels_headers = headers
            self.last_pexels_params = params
            if self.fail_pexels:
                raise requests.ConnectionError("pexels down")
            return FakeResponse(
                json_data={"videos": self.pexels.get(params["query"], [])})
        if url.startswith("https://pixabay.com"):
            self.calls.append(("pixabay", params["q"]))
            self.last_pixabay_params = params
            return FakeResponse(
                json_data={"hits": self.pixabay.get(params["q"], [])})
        self.calls.append(("download", url))
        if url not in self.downloads:
            raise requests.ConnectionError(f"unknown url {url}")
        return FakeResponse(content=self.downloads[url])


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(footage.requests, "get", fake.get)
    monkeypatch.setattr(footage.time, "sleep", lambda _s: None)
    return fake


@pytest.fixture
def project(tmp_path):
    pdir = tmp_path / "proj"
    pdir.mkdir()
    return contract.Project(dir=pdir)


@pytest.fixture
def cfg(tmp_path):
    return {
        "video": {"aspect_ratio": "9:16"},
        "footage": {
            "providers": ["pexels", "pixabay"],
            "min_height": 1080,
            "orientation": "portrait",
            # absolute path so tests never touch the real repo assets/
            "used_clip_log": str(tmp_path / "assets" / "used_clips.json"),
        },
    }


# --------------------------------------------------------------------------
# Provider behavior
# --------------------------------------------------------------------------

def test_pexels_picks_smallest_adequate_file(api):
    api.pexels["desert"] = [pexels_video(11, 20, [
        (2160, 3840, "https://cdn.test/4k.mp4"),
        (1080, 1920, "https://cdn.test/hd.mp4"),
        (540, 960, "https://cdn.test/sd.mp4"),
    ])]
    got = footage.PexelsProvider("px-key").search("desert", "portrait", 1080, 8)
    assert [c.download_url for c in got] == ["https://cdn.test/hd.mp4"]
    c = got[0]
    assert (c.provider, c.clip_id, c.width, c.height, c.duration_s) == \
        ("pexels", "11", 1080, 1920, 20.0)
    assert api.last_pexels_headers == {"Authorization": "px-key"}
    assert api.last_pexels_params == {
        "query": "desert", "orientation": "portrait", "per_page": 15}


def test_pexels_rejects_too_short_and_too_low_res(api):
    api.pexels["desert"] = [
        pexels_video(1, 3, [(1080, 1920, "https://cdn.test/short.mp4")]),
        pexels_video(2, 20, [(540, 960, "https://cdn.test/lowres.mp4")]),
    ]
    assert footage.PexelsProvider("k").search("desert", "portrait", 1080, 8) == []


def test_pixabay_picks_smallest_adequate_size(api):
    api.pixabay["dunes"] = [pixabay_hit(7, 15, {
        "large": (2160, 3840, "https://cdn.test/pb-large.mp4"),
        "medium": (1080, 1920, "https://cdn.test/pb-medium.mp4"),
        "small": (540, 960, "https://cdn.test/pb-small.mp4"),
    })]
    got = footage.PixabayProvider("pb-key").search("dunes", "portrait", 1080, 8)
    assert [c.download_url for c in got] == ["https://cdn.test/pb-medium.mp4"]
    assert (got[0].provider, got[0].clip_id) == ("pixabay", "7")
    assert api.last_pixabay_params == {
        "key": "pb-key", "q": "dunes", "per_page": 15}


def test_orientation_mismatch_rejected(api):
    # landscape 4K clip must not pass a portrait search
    api.pixabay["dunes"] = [pixabay_hit(8, 15, {
        "large": (3840, 2160, "https://cdn.test/landscape.mp4"),
    })]
    assert footage.PixabayProvider("k").search("dunes", "portrait", 1080, 8) == []


# --------------------------------------------------------------------------
# run(): download, log, report
# --------------------------------------------------------------------------

def test_run_downloads_clip_logs_and_reports(api, project, cfg):
    project.write_json(contract.SCRIPT,
                       make_script([make_scene(1, [["desert", "aerial"]])]))
    api.pexels["desert aerial"] = [
        pexels_video(42, 20, [(1080, 1920, "https://cdn.test/42.mp4")])]
    api.downloads["https://cdn.test/42.mp4"] = b"MP4-BYTES-42"

    footage.run(project, cfg, ENV)

    clip = project.dir / "clips" / "scene_001.mp4"
    assert clip.read_bytes() == b"MP4-BYTES-42"
    log = json.loads(Path(cfg["footage"]["used_clip_log"])
                     .read_text(encoding="utf-8"))
    assert log == {"pexels:42": date.today().isoformat()}
    assert project.read_json(footage.FOOTAGE_REPORT) == [{
        "scene": 1, "status": "ok", "provider": "pexels", "clip_id": "42",
        "query": "desert aerial", "width": 1080, "height": 1920,
        "duration_s": 20.0,
    }]


def test_keyword_fallback_order(api, project, cfg):
    project.write_json(contract.SCRIPT, make_script(
        [make_scene(1, [["camel caravan"], ["desert sunset"]])]))
    api.pexels["desert sunset"] = [
        pexels_video(5, 20, [(1080, 1920, "https://cdn.test/5.mp4")])]
    api.downloads["https://cdn.test/5.mp4"] = b"5"

    footage.run(project, cfg, ENV)

    searches = [c for c in api.calls if c[0] != "download"]
    assert searches == [
        ("pexels", "camel caravan"),   # set 1, provider order
        ("pixabay", "camel caravan"),
        ("pexels", "desert sunset"),   # set 2: first match wins, stop
    ]
    report = project.read_json(footage.FOOTAGE_REPORT)
    assert report[0]["status"] == "ok"
    assert report[0]["query"] == "desert sunset"


def test_used_clips_are_skipped(api, project, cfg):
    project.write_json(contract.SCRIPT,
                       make_script([make_scene(1, [["desert"]])]))
    api.pexels["desert"] = [
        pexels_video(1, 20, [(1080, 1920, "https://cdn.test/1.mp4")]),
        pexels_video(2, 20, [(1080, 1920, "https://cdn.test/2.mp4")]),
    ]
    api.downloads["https://cdn.test/2.mp4"] = b"2"
    log_path = Path(cfg["footage"]["used_clip_log"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({"pexels:1": "2026-06-01"}),
                        encoding="utf-8")

    footage.run(project, cfg, ENV)

    assert project.read_json(footage.FOOTAGE_REPORT)[0]["clip_id"] == "2"
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["pexels:1"] == "2026-06-01"  # prior entries preserved
    assert log["pexels:2"] == date.today().isoformat()


def test_unmatched_scene_is_reported_not_raised(api, project, cfg):
    project.write_json(contract.SCRIPT, make_script([
        make_scene(1, [["nothing here"], ["still nothing"]]),
        make_scene(2, [["oasis palm trees"]]),
    ]))
    api.pexels["oasis palm trees"] = [
        pexels_video(9, 20, [(1080, 1920, "https://cdn.test/9.mp4")])]
    api.downloads["https://cdn.test/9.mp4"] = b"9"

    footage.run(project, cfg, ENV)  # must not raise

    report = {e["scene"]: e
              for e in project.read_json(footage.FOOTAGE_REPORT)}
    assert report[1] == {"scene": 1, "status": "unmatched",
                         "tried": ["nothing here", "still nothing"]}
    assert report[2]["status"] == "ok"
    assert not (project.dir / "clips" / "scene_001.mp4").exists()
    assert (project.dir / "clips" / "scene_002.mp4").exists()


# --------------------------------------------------------------------------
# run(): subsetting, idempotency, key handling
# --------------------------------------------------------------------------

def test_redo_flow_refetches_only_missing_scenes(api, project, cfg):
    """The redo path deletes a scene's clip and re-runs the stage: scenes
    whose clips are still on disk must not be searched again."""
    project.write_json(contract.SCRIPT, make_script(
        [make_scene(1, [["one"]]), make_scene(2, [["two"]])]))
    (project.clips_dir / "scene_001.mp4").write_bytes(b"KEPT")
    api.pexels["two"] = [
        pexels_video(22, 20, [(1080, 1920, "https://cdn.test/22.mp4")])]
    api.downloads["https://cdn.test/22.mp4"] = b"22"

    footage.run(project, cfg, ENV)

    assert all(q != "one" for kind, q in api.calls)
    assert (project.dir / "clips" / "scene_002.mp4").exists()
    assert (project.dir / "clips" / "scene_001.mp4").read_bytes() == b"KEPT"


def test_existing_clip_skipped_unless_force(api, project, cfg):
    project.write_json(contract.SCRIPT,
                       make_script([make_scene(1, [["desert"]])]))
    clip = project.clips_dir / "scene_001.mp4"
    clip.write_bytes(b"OLD")

    footage.run(project, cfg, ENV)
    assert clip.read_bytes() == b"OLD"
    assert api.calls == []  # no search, no download
    # a pure no-op re-run must not (re)write the report either
    assert not project.has(footage.FOOTAGE_REPORT)

    api.pexels["desert"] = [
        pexels_video(3, 20, [(1080, 1920, "https://cdn.test/3.mp4")])]
    api.downloads["https://cdn.test/3.mp4"] = b"NEW"
    footage.run(project, cfg, ENV, force=True)
    assert clip.read_bytes() == b"NEW"
    assert project.read_json(footage.FOOTAGE_REPORT)[0]["status"] == "ok"


def test_all_clips_on_disk_needs_no_api_key(api, project, cfg):
    """CLAUDE.md rule 5: outputs already on disk -> return without redoing
    work — including without demanding a provider key (key rotation and the
    manual-clips workflow must not dead-end the pipeline)."""
    project.write_json(contract.SCRIPT,
                       make_script([make_scene(1, [["desert"]])]))
    (project.clips_dir / "scene_001.mp4").write_bytes(b"MANUAL")

    footage.run(project, cfg, {})  # no keys at all: must not raise

    assert api.calls == []
    assert (project.clips_dir / "scene_001.mp4").read_bytes() == b"MANUAL"


def test_missing_both_keys_is_contract_error(api, project, cfg):
    project.write_json(contract.SCRIPT,
                       make_script([make_scene(1, [["x"]])]))
    with pytest.raises(ContractError):
        footage.run(project, cfg, {})


def test_single_key_uses_only_that_provider(api, project, cfg):
    project.write_json(contract.SCRIPT,
                       make_script([make_scene(1, [["dunes"]])]))
    api.pixabay["dunes"] = [
        pixabay_hit(7, 15, {"medium": (1080, 1920, "https://cdn.test/7.mp4")})]
    api.downloads["https://cdn.test/7.mp4"] = b"7"

    footage.run(project, cfg, {"PIXABAY_API_KEY": "pb-key"})

    assert all(kind != "pexels" for kind, _ in api.calls)
    assert (project.dir / "clips" / "scene_001.mp4").read_bytes() == b"7"


def test_provider_outage_retries_then_falls_back(api, project, cfg):
    project.write_json(contract.SCRIPT,
                       make_script([make_scene(1, [["dunes"]])]))
    api.fail_pexels = True
    api.pixabay["dunes"] = [
        pixabay_hit(7, 15, {"medium": (1080, 1920, "https://cdn.test/7.mp4")})]
    api.downloads["https://cdn.test/7.mp4"] = b"7"

    footage.run(project, cfg, ENV)

    # 3 backoff attempts against the dead provider, then the backup serves
    assert [c for c in api.calls if c[0] == "pexels"] == \
        [("pexels", "dunes")] * 3
    assert (project.dir / "clips" / "scene_001.mp4").read_bytes() == b"7"


def test_redo_run_merges_report(api, project, cfg):
    project.write_json(contract.SCRIPT, make_script(
        [make_scene(1, [["one"]]), make_scene(2, [["two"]])]))
    api.pexels["one"] = [
        pexels_video(1, 20, [(1080, 1920, "https://cdn.test/1.mp4")])]
    api.downloads["https://cdn.test/1.mp4"] = b"1"

    footage.run(project, cfg, ENV)
    report = {e["scene"]: e
              for e in project.read_json(footage.FOOTAGE_REPORT)}
    assert report[1]["status"] == "ok"
    assert report[2]["status"] == "unmatched"

    # redo loop: scene 2 still has no clip, results now available
    api.pexels["two"] = [
        pexels_video(2, 20, [(1080, 1920, "https://cdn.test/2.mp4")])]
    api.downloads["https://cdn.test/2.mp4"] = b"2"
    footage.run(project, cfg, ENV)
    report = {e["scene"]: e
              for e in project.read_json(footage.FOOTAGE_REPORT)}
    assert report[1]["status"] == "ok"  # scene 1 entry survives the redo
    assert report[2]["status"] == "ok"


def test_download_rejects_html_error_body(tmp_path, monkeypatch):
    """An error page (text/html) served as HTTP 200 must not be saved as a
    clip: retried, then failed cleanly, leaving no file behind."""
    from pipeline.errors import StageError

    calls = []

    def fake_get(url, stream=False, timeout=None, **kw):
        calls.append(url)
        return FakeResponse(content=b"<html>error</html>",
                            headers={"Content-Type": "text/html; charset=utf-8"})

    monkeypatch.setattr(footage.requests, "get", fake_get)
    monkeypatch.setattr(footage.time, "sleep", lambda s: None)
    dest = tmp_path / "clip.mp4"
    with pytest.raises(StageError):
        footage._download("http://cdn/clip.mp4", dest)
    assert not dest.exists()
    assert len(calls) == footage._ATTEMPTS  # retried, then failed
