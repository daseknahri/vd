# -*- coding: utf-8 -*-
"""Publish stage tests. No network, no posting — metadata generation plus
the engagement-bait and auto-post defenses."""

import copy
from datetime import datetime

import pytest

from pipeline import contract, publish
from pipeline.contract import ContractError, Project

CFG = {"footage": {"ai_broll": False}, "publish": {"auto_post": False}}

SCRIPT_DATA = {
    "meta": {
        "source_url": "https://example.com/v",
        "audience": "general Arab",
        "dialect": "MSA",
        "target_seconds": 90,
    },
    "hook": "لن تصدق ما ستراه الآن",
    "scenes": [
        {
            "id": 1,
            "narration_ar": "مدينة عملاقة وسط الصحراء",
            "keywords": [["aerial desert city"]],
            "mood": "calm",
            "target_seconds": 8,
        },
    ],
    "post": {
        "title": "مدينة المستقبل في الصحراء",
        "description": "رحلة قصيرة داخل أضخم مشروع بناء في العالم.",
        "hashtags": ["#تقنية", "#عمران"],
    },
}


def _make_project(tmp_path, post=None):
    d = tmp_path / "2026-06-12-test"
    d.mkdir()
    project = Project(dir=d)
    script = copy.deepcopy(SCRIPT_DATA)
    if post:
        script["post"].update(post)
    project.write_json(contract.SCRIPT, script)
    return project


# -- clean post ----------------------------------------------------------------

def test_clean_post_writes_post_json(tmp_path):
    project = _make_project(tmp_path)
    publish.run(project, CFG, {})

    data = project.read_json(contract.POST)
    assert data["title"] == SCRIPT_DATA["post"]["title"]
    assert data["description"] == SCRIPT_DATA["post"]["description"]
    assert data["hashtags"] == ["#تقنية", "#عمران"]
    assert data["needs_ai_label"] is False
    assert data["runtime_seconds"] is None      # no timing.json yet
    # parseable ISO timestamp
    assert datetime.fromisoformat(data["generated_at"])


def test_runtime_seconds_comes_from_timing(tmp_path):
    project = _make_project(tmp_path)
    project.write_json(contract.TIMING, {
        "total_seconds": 83.2,
        "scenes": [{"id": 1, "start": 0.0, "end": 83.2, "words": []}],
    })
    publish.run(project, CFG, {})
    assert project.read_json(contract.POST)["runtime_seconds"] == 83.2


def test_needs_ai_label_follows_cfg(tmp_path):
    project = _make_project(tmp_path)
    cfg = {"footage": {"ai_broll": True}, "publish": {"auto_post": False}}
    publish.run(project, cfg, {})
    assert project.read_json(contract.POST)["needs_ai_label"] is True


# -- banned-phrase defense -------------------------------------------------------

def test_bait_in_description_raises_listing_phrase(tmp_path):
    project = _make_project(tmp_path, post={
        "description": "أجمل مدينة في العالم! لا تنس الاشتراك في القناة",
    })
    with pytest.raises(ContractError) as exc:
        publish.run(project, CFG, {})
    assert "لا تنس الاشتراك" in str(exc.value)
    assert "description" in str(exc.value)
    assert not project.has(contract.POST)


def test_bait_with_diacritics_still_caught(tmp_path):
    project = _make_project(tmp_path, post={
        "description": "لا تَنْسَ الاشتراك معنا",
    })
    with pytest.raises(ContractError):
        publish.run(project, CFG, {})


def test_english_bait_in_title_raises(tmp_path):
    project = _make_project(tmp_path, post={"title": "You should Subscribe!"})
    with pytest.raises(ContractError) as exc:
        publish.run(project, CFG, {})
    assert "subscribe" in str(exc.value)
    assert "title" in str(exc.value)


def test_bait_in_hashtags_raises(tmp_path):
    project = _make_project(tmp_path, post={"hashtags": ["#علوم", "#لايك"]})
    with pytest.raises(ContractError) as exc:
        publish.run(project, CFG, {})
    assert "لايك" in str(exc.value)
    assert "hashtags" in str(exc.value)


def test_legit_words_containing_banned_substrings_pass(tmp_path):
    # يشير/تشير contain شير; must not be flagged (word-boundary anchoring)
    project = _make_project(tmp_path, post={
        "description": "تشير الدراسات إلى نمو هائل، كما يشير الخبراء.",
    })
    publish.run(project, CFG, {})
    assert project.has(contract.POST)


def test_banned_phrases_file_is_loaded(tmp_path):
    phrases = publish._load_banned_phrases()
    assert len(phrases) >= 15
    assert "subscribe" in phrases
    assert any("اشترك في القناة" == p for p in phrases)
    assert all(not p.startswith("#") for p in phrases)


# -- auto-post defense ------------------------------------------------------------

def test_auto_post_true_raises(tmp_path):
    project = _make_project(tmp_path)
    cfg = {"publish": {"auto_post": True}}
    with pytest.raises(ContractError, match="auto-posting is disabled"):
        publish.run(project, cfg, {})


def test_auto_post_raises_even_if_output_exists(tmp_path):
    project = _make_project(tmp_path)
    publish.run(project, CFG, {})
    with pytest.raises(ContractError, match="PLAN.md 3.6"):
        publish.run(project, {"publish": {"auto_post": True}}, {})


# -- idempotency / errors ----------------------------------------------------------

def test_idempotent_skip_and_force_rerun(tmp_path):
    project = _make_project(tmp_path)
    publish.run(project, CFG, {})
    first = project.read_json(contract.POST)

    script = project.read_json(contract.SCRIPT)
    script["post"]["title"] = "عنوان جديد تماما"
    project.write_json(contract.SCRIPT, script)

    publish.run(project, CFG, {})               # output exists -> early return
    assert project.read_json(contract.POST)["title"] == first["title"]

    publish.run(project, CFG, {}, force=True)
    assert project.read_json(contract.POST)["title"] == "عنوان جديد تماما"


def test_missing_script_raises_contract_error(tmp_path):
    # Missing contracted input -> ContractError (consistent across stages).
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ContractError, match="script.json"):
        publish.run(Project(dir=d), CFG, {})
