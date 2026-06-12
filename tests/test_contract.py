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
