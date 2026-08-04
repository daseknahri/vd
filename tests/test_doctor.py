"""Tests for pipeline/doctor.py and the `run.py doctor` command.

Toolchain checks are forced to their failure state by monkeypatching the
thing they probe (ffmpeg resolution, Pillow's raqm feature); go-live checks
are driven purely by the cfg/env dicts, so most tests need no real files.
"""

from __future__ import annotations

import pytest

import run as runner
from pipeline import contract, doctor

# Minimal healthy config: real caption font (assets/fonts exists in-repo),
# a set voice id, and a music dir. Individual tests override one slice.
BASE_CFG = {
    "captions": {"font": "Tajawal"},
    "voice": {"voice_id": "abc123"},
    "audio": {"music_dir": "assets/music"},
}


def find(checks, name):
    return next(c for c in checks if c.name == name)


# --------------------------------------------------------------------------
# Toolchain checks (required -> can FAIL the result)
# --------------------------------------------------------------------------

def test_missing_ffmpeg_is_a_toolchain_failure(monkeypatch):
    def boom(tool="ffmpeg"):
        raise FileNotFoundError(f"{tool} not found")

    monkeypatch.setattr(contract, "ffmpeg_path", boom)
    checks = doctor.run_checks(BASE_CFG, {}, None)
    ff = find(checks, "ffmpeg")
    assert ff.status == doctor.FAIL and ff.required is True
    assert doctor.has_failures(checks)


def test_raqm_missing_is_a_toolchain_failure(monkeypatch):
    from PIL import features

    monkeypatch.setattr(features, "check", lambda name: False)
    checks = doctor.run_checks(BASE_CFG, {}, None)
    raqm = find(checks, "pillow raqm")
    assert raqm.status == doctor.FAIL and raqm.required is True


def test_config_parse_error_is_reported_as_failure():
    checks = doctor.run_checks(None, {}, "config.yaml is not valid YAML: boom")
    c = find(checks, "config.yaml")
    assert c.status == doctor.FAIL and c.required is True
    assert doctor.has_failures(checks)


def test_unknown_caption_font_fails():
    cfg = {**BASE_CFG, "captions": {"font": "NoSuchFontFamily"}}
    assert find(doctor.run_checks(cfg, {}, None), "caption font").status == doctor.FAIL


def test_caption_font_resolves_in_a_healthy_repo():
    assert find(doctor.run_checks(BASE_CFG, {}, None), "caption font").status == doctor.OK


# --------------------------------------------------------------------------
# Go-live checks (not required -> only ever WARN, never fail the result)
# --------------------------------------------------------------------------

def test_env_keys_warn_when_absent():
    checks = doctor.run_checks(BASE_CFG, {}, None)
    assert find(checks, "ELEVENLABS_API_KEY").status == doctor.WARN
    assert find(checks, "footage key").status == doctor.WARN


def test_env_keys_ok_when_present():
    env = {"ELEVENLABS_API_KEY": "k", "PEXELS_API_KEY": "p"}
    checks = doctor.run_checks(BASE_CFG, env, None)
    assert find(checks, "ELEVENLABS_API_KEY").status == doctor.OK
    assert find(checks, "footage key").status == doctor.OK


def test_voice_id_warns_when_empty():
    cfg = {**BASE_CFG, "voice": {"voice_id": ""}}
    assert find(doctor.run_checks(cfg, {}, None), "voice.voice_id").status == doctor.WARN


def test_music_ok_when_bed_present(tmp_path):
    (tmp_path / "bed.mp3").write_bytes(b"x")
    cfg = {**BASE_CFG, "audio": {"music_dir": str(tmp_path)}}
    assert find(doctor.run_checks(cfg, {}, None), "music bed").status == doctor.OK


def test_music_warns_when_dir_empty(tmp_path):
    cfg = {**BASE_CFG, "audio": {"music_dir": str(tmp_path)}}
    assert find(doctor.run_checks(cfg, {}, None), "music bed").status == doctor.WARN


def test_golive_gaps_alone_do_not_fail_the_result():
    """Empty .env + empty voice id on a healthy toolchain: WARNs, no FAIL."""
    cfg = {**BASE_CFG, "voice": {"voice_id": ""}}
    checks = doctor.run_checks(cfg, {}, None)
    assert not doctor.has_failures(checks)
    assert any(c.status == doctor.WARN for c in checks)


# --------------------------------------------------------------------------
# has_failures + CLI wiring
# --------------------------------------------------------------------------

def test_has_failures_only_on_fail():
    assert not doctor.has_failures([doctor.Check("x", doctor.OK, "", True)])
    assert not doctor.has_failures([doctor.Check("x", doctor.WARN, "", False)])
    assert doctor.has_failures([doctor.Check("x", doctor.FAIL, "", True)])


def test_doctor_cli_prints_grouped_report_and_exits_zero(capsys):
    # Toolchain is healthy in this repo/CI env (same assumption the ffmpeg
    # render tests already make), so the command exits 0.
    rc = runner.main(["doctor"])
    out = capsys.readouterr().out
    assert "preflight check" in out
    assert "toolchain (required):" in out
    assert "go-live" in out
    assert rc == 0


def test_doctor_cli_exits_one_when_toolchain_broken(monkeypatch, capsys):
    def boom(tool="ffmpeg"):
        raise FileNotFoundError(f"{tool} not found")

    monkeypatch.setattr(contract, "ffmpeg_path", boom)
    rc = runner.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED" in out
