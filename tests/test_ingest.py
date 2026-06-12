"""Ingest stage tests. No network, no real yt-dlp or whisper model:
fake modules are injected into sys.modules before run() lazy-imports them.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import contract, ingest
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

CFG = {"transcribe": {"model": "small", "device": "cpu", "compute_type": "int8"}}
URL = "https://example.com/watch?v=abc123"


def make_project(tmp_path: Path, url: str = URL) -> Project:
    project = Project(dir=tmp_path)
    project.write_text(contract.SOURCE_URL, url + "\n")
    return project


def seg(text: str, start: float, end: float) -> SimpleNamespace:
    return SimpleNamespace(text=text, start=start, end=end)


# Gap between segment 2 and 3 (4.0 -> 7.0) forces a paragraph break.
DEFAULT_SEGMENTS = [
    seg(" مرحبا بكم", 0.0, 2.0),
    seg("في هذا الفيديو ", 2.1, 4.0),
    seg("فقرة جديدة تماما", 7.0, 9.0),
]
EXPECTED_TRANSCRIPT = "مرحبا بكم في هذا الفيديو\n\nفقرة جديدة تماما\n"


@pytest.fixture
def fakes(monkeypatch):
    """Install fake yt_dlp / faster_whisper modules; return call state."""
    state = {
        "ydl_calls": [],
        "whisper_calls": [],
        "download_error": None,
        "segments": list(DEFAULT_SEGMENTS),
        "ext": "webm",
    }

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            state["ydl_calls"].append(
                {"url": url, "opts": self.opts, "download": download}
            )
            if state["download_error"] is not None:
                raise state["download_error"]
            out = Path(self.opts["outtmpl"] % {"ext": state["ext"]})
            out.write_bytes(b"fake-audio-bytes")
            return {
                "title": "How Volcanoes Work",
                "duration": 432,
                "uploader": "Some Channel",
            }

    class FakeWhisperModel:
        def __init__(self, model, device=None, compute_type=None):
            state["whisper_calls"].append(("init", model, device, compute_type))

        def transcribe(self, path, **kwargs):
            state["whisper_calls"].append(("transcribe", str(path)))
            info = SimpleNamespace(language="ar", language_probability=0.98)
            return iter(state["segments"]), info

    fake_yt = types.ModuleType("yt_dlp")
    fake_yt.YoutubeDL = FakeYoutubeDL
    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_yt)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    return state


def test_run_writes_transcript_audio_and_report(tmp_path, fakes):
    project = make_project(tmp_path)
    ingest.run(project, CFG, {})

    assert project.read_text(contract.TRANSCRIPT) == EXPECTED_TRANSCRIPT

    audio = tmp_path / "source_audio.webm"
    assert audio.exists()

    report = project.read_json(ingest.INGEST_REPORT)
    assert report["source_url"] == URL
    assert report["audio_file"] == "source_audio.webm"
    assert report["title"] == "How Volcanoes Work"
    assert report["duration"] == 432
    assert report["uploader"] == "Some Channel"
    assert report["language"] == "ar"
    assert report["segments"] == 3

    (call,) = fakes["ydl_calls"]
    assert call["url"] == URL
    assert call["opts"]["format"].startswith("bestaudio")
    assert call["opts"]["outtmpl"] == str(tmp_path / "source_audio.%(ext)s")

    assert ("init", "small", "cpu", "int8") in fakes["whisper_calls"]
    assert ("transcribe", str(audio)) in fakes["whisper_calls"]


def test_idempotent_skip_when_transcript_exists(tmp_path, fakes):
    project = make_project(tmp_path)
    project.write_text(contract.TRANSCRIPT, "already here\n")
    ingest.run(project, CFG, {})
    assert fakes["ydl_calls"] == []
    assert fakes["whisper_calls"] == []
    assert project.read_text(contract.TRANSCRIPT) == "already here\n"


def test_force_redownloads_and_rewrites(tmp_path, fakes):
    project = make_project(tmp_path)
    project.write_text(contract.TRANSCRIPT, "stale\n")
    ingest.run(project, CFG, {}, force=True)
    assert len(fakes["ydl_calls"]) == 1
    assert project.read_text(contract.TRANSCRIPT) == EXPECTED_TRANSCRIPT


def test_missing_source_url_raises_contract_error(tmp_path, fakes):
    project = Project(dir=tmp_path)
    with pytest.raises(ContractError):
        ingest.run(project, CFG, {})
    assert fakes["ydl_calls"] == []


def test_blank_source_url_raises_contract_error(tmp_path, fakes):
    project = make_project(tmp_path, url="   ")
    with pytest.raises(ContractError):
        ingest.run(project, CFG, {})


def test_missing_transcribe_config_raises_contract_error(tmp_path, fakes):
    project = make_project(tmp_path)
    with pytest.raises(ContractError):
        ingest.run(project, {}, {})
    assert fakes["ydl_calls"] == []


def test_download_failure_raises_stage_error(tmp_path, fakes):
    fakes["download_error"] = RuntimeError("HTTP Error 403: Forbidden")
    project = make_project(tmp_path)
    with pytest.raises(StageError) as exc_info:
        ingest.run(project, CFG, {})
    assert exc_info.value.stage == "ingest"
    assert fakes["whisper_calls"] == []
    assert not project.has(contract.TRANSCRIPT)


def test_existing_audio_skips_download(tmp_path, fakes):
    project = make_project(tmp_path)
    (tmp_path / "source_audio.m4a").write_bytes(b"left over from a crash")
    ingest.run(project, CFG, {})
    assert fakes["ydl_calls"] == []
    assert project.read_text(contract.TRANSCRIPT) == EXPECTED_TRANSCRIPT
    report = project.read_json(ingest.INGEST_REPORT)
    assert report["audio_file"] == "source_audio.m4a"


def test_partial_download_leftovers_trigger_redownload(tmp_path, fakes):
    """yt-dlp writes source_audio.<ext>.part (and a .ytdl state file) while
    downloading and renames only on completion. Leftovers from a crashed
    download must never be transcribed as if they were the finished audio."""
    project = make_project(tmp_path)
    (tmp_path / "source_audio.m4a.part").write_bytes(b"truncated half-file")
    (tmp_path / "source_audio.ytdl").write_bytes(b"{}")

    ingest.run(project, CFG, {})

    assert len(fakes["ydl_calls"]) == 1  # re-downloaded, not resumed
    report = project.read_json(ingest.INGEST_REPORT)
    assert report["audio_file"] == "source_audio.webm"  # the fresh download
    assert ("transcribe", str(tmp_path / "source_audio.webm")) in fakes[
        "whisper_calls"]


def test_empty_transcription_raises_stage_error(tmp_path, fakes):
    fakes["segments"] = []
    project = make_project(tmp_path)
    with pytest.raises(StageError) as exc_info:
        ingest.run(project, CFG, {})
    assert exc_info.value.stage == "ingest"
    assert not project.has(contract.TRANSCRIPT)


def test_segments_without_timing_become_one_paragraph(tmp_path, fakes):
    # Fakes that expose only .text (no start/end) must still transcribe.
    fakes["segments"] = [
        SimpleNamespace(text="جملة اولى"),
        SimpleNamespace(text="جملة ثانية"),
    ]
    project = make_project(tmp_path)
    ingest.run(project, CFG, {})
    assert project.read_text(contract.TRANSCRIPT) == "جملة اولى جملة ثانية\n"


def test_module_import_never_loads_whisper(monkeypatch):
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)
    monkeypatch.delitem(sys.modules, "yt_dlp", raising=False)
    importlib.reload(ingest)
    assert "faster_whisper" not in sys.modules
    assert "yt_dlp" not in sys.modules
