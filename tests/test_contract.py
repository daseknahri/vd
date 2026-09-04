"""Contract-layer tests: garbled contracted files must surface as
ContractError (which the orchestrator records, so batch mode keeps going),
never escape as raw JSONDecodeError / YAMLError."""

from __future__ import annotations

import json

import pytest

from pipeline import contract
from pipeline.contract import ContractError, Project


def test_read_json_malformed_raises_contract_error(tmp_path):
    proj = Project(dir=tmp_path)
    proj.write_text(contract.SCRIPT, "{ this is not valid json")
    with pytest.raises(ContractError, match="not valid JSON") as exc:
        proj.read_json(contract.SCRIPT)
    assert contract.SCRIPT in str(exc.value)
    # the typed accessors inherit the guard
    with pytest.raises(ContractError):
        proj.script()


def test_read_json_valid_still_works(tmp_path):
    proj = Project(dir=tmp_path)
    proj.write_json("x.json", {"ok": True})
    assert proj.read_json("x.json") == {"ok": True}


def test_timing_and_pronunciation_malformed_raise_contract_error(tmp_path):
    proj = Project(dir=tmp_path)
    proj.write_text(contract.TIMING, "[1, 2,")
    with pytest.raises(ContractError, match="not valid JSON"):
        proj.timing()
    proj.write_text(contract.PRONUNCIATION, "{broken")
    with pytest.raises(ContractError, match="not valid JSON"):
        proj.pronunciation_overrides()


# -- optional per-scene broll_prompt (generated B-roll) -----------------------
def _valid_script(scene_extra=None):
    scene = {"id": 1, "narration_ar": "نص قصير", "keywords": [["desert dunes"]],
             "mood": "calm", "target_seconds": 8}
    if scene_extra:
        scene.update(scene_extra)
    return {
        "meta": {"source_url": "u", "audience": "general Arab",
                 "dialect": "MSA", "target_seconds": 90},
        "hook": "hook line", "scenes": [scene],
        "post": {"title": "", "description": "", "hashtags": []},
    }


def test_validate_script_accepts_optional_broll_prompt():
    contract.validate_script(_valid_script({"broll_prompt": "a cinematic desert shot at dusk"}))


def test_validate_script_accepts_missing_broll_prompt():
    contract.validate_script(_valid_script())   # backward compatible


def test_validate_script_rejects_bad_broll_prompt():
    for bad in ("", "   ", 123, ["x"]):
        with pytest.raises(ContractError, match="broll_prompt"):
            contract.validate_script(_valid_script({"broll_prompt": bad}))


def test_load_config_malformed_project_yaml_raises_contract_error(tmp_path):
    (tmp_path / contract.PROJECT_CONFIG).write_text(
        "video: [unclosed", encoding="utf-8")
    with pytest.raises(ContractError, match="not valid YAML"):
        contract.load_config(tmp_path)


def test_load_config_merges_valid_project_yaml(tmp_path):
    (tmp_path / contract.PROJECT_CONFIG).write_text(
        "video:\n  fps: 12\n", encoding="utf-8")
    cfg = contract.load_config(tmp_path)
    assert cfg["video"]["fps"] == 12


def test_gate_revoke_removes_marker(tmp_path):
    proj = Project(dir=tmp_path)
    proj.approve_gate(contract.GATE2_APPROVED)
    assert proj.gate_approved(contract.GATE2_APPROVED)
    proj.revoke_gate(contract.GATE2_APPROVED)
    assert not proj.gate_approved(contract.GATE2_APPROVED)
    proj.revoke_gate(contract.GATE2_APPROVED)  # idempotent on a missing marker
