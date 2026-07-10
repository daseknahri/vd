"""Orchestrator (run.py) + script stage tests.

Stage modules are replaced by recorder fakes injected into sys.modules
before run.py lazily imports them — no network, no ffmpeg, no real stages.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

import run as runner
from pipeline import contract
from pipeline import script as script_stage
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

URL = "https://example.com/videos/volcanoes"

VALID_SCRIPT = {
    "meta": {
        "source_url": URL,
        "audience": "general Arab",
        "dialect": "MSA",
        "target_seconds": 90,
    },
    "hook": "هل تعلم أن البراكين تتنفس؟",
    "scenes": [
        {
            "id": 1,
            "narration_ar": "نص المشهد الأول",
            "keywords": [["volcano eruption aerial"]],
            "mood": "energetic",
            "target_seconds": 8,
        },
        {
            "id": 2,
            "narration_ar": "نص المشهد الثاني",
            "keywords": [["lava flow night"], ["red glow rock"]],
            "mood": "calm",
            "target_seconds": 9,
        },
    ],
    "post": {"title": "عنوان", "description": "وصف", "hashtags": ["#علوم"]},
}

ALL_STAGES = ["ingest", "script", "voice", "footage", "captions",
              "render", "review", "publish"]


@pytest.fixture
def recorders(monkeypatch):
    """Replace every stage module with a recording fake in sys.modules.

    state["errors"][stage] may hold a callable(project) -> exception | None
    to make a stage fail for specific projects.
    """
    calls: list[dict] = []
    state: dict = {"errors": {}}

    def make(stage_name):
        def fake_run(project, cfg, env, *, force=False, **kwargs):
            calls.append({
                "stage": stage_name,
                "project": Path(project.dir),
                "force": force,
                **kwargs,
            })
            err_fn = state["errors"].get(stage_name)
            if err_fn is not None:
                exc = err_fn(project)
                if exc is not None:
                    raise exc
        return fake_run

    for stage_name, mod in runner.STAGE_MODULES.items():
        fake = types.ModuleType(f"pipeline.{mod}")
        fake.run = make(stage_name)
        monkeypatch.setitem(sys.modules, f"pipeline.{mod}", fake)
    return {"calls": calls, "state": state}


@pytest.fixture
def project(tmp_path):
    pdir = tmp_path / "2026-06-12-test-project"
    pdir.mkdir()
    p = Project(dir=pdir)
    p.write_text(contract.SOURCE_URL, URL + "\n")
    return p


def stages_called(recorders) -> list[str]:
    return [c["stage"] for c in recorders["calls"]]


# --------------------------------------------------------------------------
# process: stage order + gates
# --------------------------------------------------------------------------

def test_process_runs_all_stages_in_order_when_gates_approved(project, recorders):
    project.approve_gate(contract.GATE1_APPROVED)
    project.approve_gate(contract.GATE2_APPROVED)
    rc = runner.main(["process", str(project.dir)])
    assert rc == 0
    assert stages_called(recorders) == ALL_STAGES


def test_process_stops_at_gate1_voice_never_called(project, recorders, capsys):
    rc = runner.main(["process", str(project.dir)])
    assert rc == 0  # designed stop, not a failure
    assert stages_called(recorders) == ["ingest", "script"]
    out = capsys.readouterr().out
    assert "GATE 1" in out
    assert str(project.path(contract.SCRIPT)) in out
    # The exact approve command is printed.
    assert f'python run.py approve "{project.dir}" --gate 1' in out


def test_process_resumes_after_gate1_then_stops_at_gate2(project, recorders, capsys):
    project.approve_gate(contract.GATE1_APPROVED)
    rc = runner.main(["process", str(project.dir)])
    assert rc == 0
    assert stages_called(recorders) == [
        "ingest", "script", "voice", "footage", "captions", "render", "review",
    ]
    out = capsys.readouterr().out
    assert "GATE 2" in out
    assert str(project.path(contract.CONTACT_SHEET)) in out
    assert f'python run.py approve "{project.dir}" --gate 2' in out


def test_full_gate_cycle_ends_with_publish(project, recorders):
    assert runner.main(["process", str(project.dir)]) == 0           # gate 1
    assert runner.main(["approve", str(project.dir), "--gate", "1"]) == 0
    assert runner.main(["process", str(project.dir)]) == 0           # gate 2
    assert runner.main(["approve", str(project.dir), "--gate", "2"]) == 0
    assert runner.main(["process", str(project.dir)]) == 0
    assert stages_called(recorders)[-1] == "publish"
    assert stages_called(recorders).count("publish") == 1


def test_process_default_force_is_false(project, recorders):
    project.approve_gate(contract.GATE1_APPROVED)
    project.approve_gate(contract.GATE2_APPROVED)
    runner.main(["process", str(project.dir)])
    assert all(c["force"] is False for c in recorders["calls"])


def test_force_stage_forces_only_that_stage(project, recorders):
    project.approve_gate(contract.GATE1_APPROVED)
    project.approve_gate(contract.GATE2_APPROVED)
    rc = runner.main(["process", str(project.dir), "--force-stage", "render"])
    assert rc == 0
    forces = {c["stage"]: c["force"] for c in recorders["calls"]}
    assert forces["render"] is True
    assert all(v is False for s, v in forces.items() if s != "render")


def test_process_stage_error_exits_one(project, recorders, capsys):
    recorders["state"]["errors"]["ingest"] = (
        lambda p: StageError("ingest", "download exploded")
    )
    rc = runner.main(["process", str(project.dir)])
    assert rc == 1
    assert "[ingest] download exploded" in capsys.readouterr().out


def test_process_missing_project_dir_exits_one(tmp_path, capsys):
    rc = runner.main(["process", str(tmp_path / "does-not-exist")])
    assert rc == 1
    assert "not found" in capsys.readouterr().out


# --------------------------------------------------------------------------
# approve
# --------------------------------------------------------------------------

def test_approve_writes_gate_markers(project):
    assert runner.main(["approve", str(project.dir), "--gate", "1"]) == 0
    assert project.gate_approved(contract.GATE1_APPROVED)
    assert not project.gate_approved(contract.GATE2_APPROVED)
    assert runner.main(["approve", str(project.dir), "--gate", "2"]) == 0
    assert project.gate_approved(contract.GATE2_APPROVED)


# --------------------------------------------------------------------------
# redo
# --------------------------------------------------------------------------

def test_redo_deletes_clips_refetches_and_forces_downstream(project, recorders):
    clips = project.clips_dir
    for sid in (1, 2, 3):
        (clips / f"scene_{sid:03d}.mp4").write_bytes(b"clip")
    rc = runner.main(["redo", str(project.dir), "--scenes", "1", "3"])
    assert rc == 0
    assert not (clips / "scene_001.mp4").exists()
    assert (clips / "scene_002.mp4").exists()  # untouched scene survives
    assert not (clips / "scene_003.mp4").exists()
    assert stages_called(recorders) == ["footage", "captions", "render", "review"]
    footage_call = recorders["calls"][0]
    # footage is called through the frozen stage contract — no extra kwargs
    assert footage_call["force"] is False
    assert "scene_ids" not in footage_call
    for call in recorders["calls"][1:]:
        assert call["force"] is True


def test_redo_unknown_scene_id_exits_one(project, recorders, capsys):
    project.write_json(contract.SCRIPT, VALID_SCRIPT)  # scenes 1 and 2
    (project.clips_dir / "scene_001.mp4").write_bytes(b"clip")
    rc = runner.main(["redo", str(project.dir), "--scenes", "9"])
    assert rc == 1
    assert "scenes not in script.json: [9]" in capsys.readouterr().out
    assert (project.clips_dir / "scene_001.mp4").exists()  # nothing deleted
    assert stages_called(recorders) == []


def test_redo_revokes_gate2_so_publish_needs_fresh_review(project, recorders):
    """Redo replaces the rendered content the human approved; the stale
    gate-2 marker must not let the next process run reach publish."""
    project.approve_gate(contract.GATE1_APPROVED)
    project.approve_gate(contract.GATE2_APPROVED)
    rc = runner.main(["redo", str(project.dir), "--scenes", "1"])
    assert rc == 0
    assert not project.gate_approved(contract.GATE2_APPROVED)
    assert project.gate_approved(contract.GATE1_APPROVED)  # script unchanged

    rc = runner.main(["process", str(project.dir)])
    assert rc == 0
    assert "publish" not in stages_called(recorders)  # stopped at gate 2


def test_force_stage_revokes_downstream_gate_approvals(project, recorders, capsys):
    """--force-stage regenerates content under an existing approval; gates
    after the forced stage must be re-reviewed, never sailed past."""
    project.approve_gate(contract.GATE1_APPROVED)
    project.approve_gate(contract.GATE2_APPROVED)
    rc = runner.main(["process", str(project.dir), "--force-stage", "review"])
    assert rc == 0
    assert "publish" not in stages_called(recorders)
    assert not project.gate_approved(contract.GATE2_APPROVED)
    assert project.gate_approved(contract.GATE1_APPROVED)  # upstream gate kept
    assert "GATE 2" in capsys.readouterr().out


def test_redo_failure_exits_one(project, recorders, capsys):
    recorders["state"]["errors"]["render"] = (
        lambda p: StageError("render", "ffmpeg fell over")
    )
    rc = runner.main(["redo", str(project.dir), "--scenes", "2"])
    assert rc == 1
    assert "[render] ffmpeg fell over" in capsys.readouterr().out


# --------------------------------------------------------------------------
# new
# --------------------------------------------------------------------------

def test_new_creates_project_and_writes_source_url(tmp_path, capsys):
    root = tmp_path / "projects"
    rc = runner.main(["new", URL, "--projects-root", str(root)])
    assert rc == 0
    (pdir,) = list(root.iterdir())
    assert Project(dir=pdir).read_text(contract.SOURCE_URL).strip() == URL
    out = capsys.readouterr().out
    assert "process" in out  # next step printed


def test_new_with_explicit_slug(tmp_path):
    root = tmp_path / "projects"
    rc = runner.main(["new", URL, "--slug", "My Volcano Video",
                      "--projects-root", str(root)])
    assert rc == 0
    (pdir,) = list(root.iterdir())
    assert pdir.name.endswith("-my-volcano-video")


def test_slug_from_url_keeps_query_so_watch_urls_stay_distinct():
    a = runner._slug_from_url("https://www.youtube.com/watch?v=abc123")
    b = runner._slug_from_url("https://www.youtube.com/watch?v=xyz789")
    assert a != b
    assert "youtube" in a and "watch" in a


# --------------------------------------------------------------------------
# batch
# --------------------------------------------------------------------------

def test_batch_continues_past_failing_project_and_reports(tmp_path, recorders, capsys):
    root = tmp_path / "projects"
    urls = tmp_path / "urls.txt"
    urls.write_text(
        "# comment line\n"
        "\n"
        "https://example.com/videos/alpha\n"
        "https://example.com/videos/beta\n"
        "https://example.com/videos/gamma\n",
        encoding="utf-8",
    )
    recorders["state"]["errors"]["ingest"] = lambda p: (
        StageError("ingest", "download exploded") if "beta" in p.dir.name else None
    )
    rc = runner.main(["batch", str(urls), "--projects-root", str(root)])
    assert rc == 1  # one project failed

    # beta failed at ingest; alpha and gamma still ran through script and
    # stopped at gate 1 (script.json not generated is irrelevant here —
    # the script stage is a recorder fake).
    by_project: dict[str, list[str]] = {}
    for call in recorders["calls"]:
        by_project.setdefault(call["project"].name, []).append(call["stage"])
    names = sorted(by_project)
    alpha = next(n for n in names if "alpha" in n)
    beta = next(n for n in names if "beta" in n)
    gamma = next(n for n in names if "gamma" in n)
    assert by_project[alpha] == ["ingest", "script"]
    assert by_project[beta] == ["ingest"]
    assert by_project[gamma] == ["ingest", "script"]

    out = capsys.readouterr().out
    assert "batch summary" in out
    assert "download exploded" in out
    assert "waiting at gate 1" in out
    for name in (alpha, beta, gamma):
        assert name in out


def test_batch_slug_collision_keeps_projects_distinct(tmp_path, recorders):
    """Two different URLs whose slugs share the first 40 chars must not be
    silently merged into one project (wrong source attribution)."""
    root = tmp_path / "projects"
    long_path = "a" * 60
    url_one = f"https://example.com/{long_path}/one"
    url_two = f"https://example.com/{long_path}/two"
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{url_one}\n{url_two}\n", encoding="utf-8")

    rc = runner.main(["batch", str(urls), "--projects-root", str(root)])
    assert rc == 0
    dirs = sorted(root.iterdir())
    assert len(dirs) == 2
    stored = {Project(dir=d).read_text(contract.SOURCE_URL).strip()
              for d in dirs}
    assert stored == {url_one, url_two}


def test_same_url_reuses_the_same_project(tmp_path):
    root = tmp_path / "projects"
    p1 = runner._create_project(URL, None, root)
    p2 = runner._create_project(URL, None, root)
    assert p1.dir == p2.dir  # idempotent for the same source
    assert len(list(root.iterdir())) == 1


# --------------------------------------------------------------------------
# new-topic (topic-first: no source video, ingest skipped)
# --------------------------------------------------------------------------

def test_new_topic_writes_topic_and_no_source_url(tmp_path, capsys):
    root = tmp_path / "projects"
    rc = runner.main(["new-topic", "3 facts about the Sahara",
                      "--projects-root", str(root)])
    assert rc == 0
    (pdir,) = list(root.iterdir())
    p = Project(dir=pdir)
    assert p.read_text(contract.TOPIC).strip() == "3 facts about the Sahara"
    assert not p.has(contract.SOURCE_URL)
    assert p.is_topic_first()
    assert "topic-first" in capsys.readouterr().out


def test_new_topic_empty_exits_one(tmp_path, capsys):
    rc = runner.main(["new-topic", "   ", "--projects-root", str(tmp_path)])
    assert rc == 1
    assert "empty topic" in capsys.readouterr().out


def test_topic_first_process_skips_ingest(tmp_path, recorders):
    """A topic-first project has no source video; process must not run
    ingest, but must still reach the script stage and stop at gate 1."""
    root = tmp_path / "projects"
    runner.main(["new-topic", "the history of coffee", "--projects-root", str(root)])
    (pdir,) = list(root.iterdir())
    rc = runner.main(["process", str(pdir)])
    assert rc == 0  # designed stop at gate 1
    assert stages_called(recorders) == ["script"]  # ingest skipped


def test_topic_first_full_run_never_ingests(tmp_path, recorders):
    root = tmp_path / "projects"
    runner.main(["new-topic", "deep sea creatures", "--projects-root", str(root)])
    (pdir,) = list(root.iterdir())
    project = Project(dir=pdir)
    project.approve_gate(contract.GATE1_APPROVED)
    project.approve_gate(contract.GATE2_APPROVED)
    rc = runner.main(["process", str(pdir)])
    assert rc == 0
    assert stages_called(recorders) == [
        "script", "voice", "footage", "captions", "render", "review", "publish",
    ]
    assert "ingest" not in stages_called(recorders)


def test_url_first_project_still_ingests(project, recorders):
    """Regression guard: the ingest-skip must be topic-first only."""
    assert not project.is_topic_first()
    runner.main(["process", str(project.dir)])
    assert stages_called(recorders)[0] == "ingest"


def test_different_topics_stay_distinct(tmp_path):
    root = tmp_path / "projects"
    p1 = runner._create_topic_project("coffee", None, root)
    p2 = runner._create_topic_project("tea", None, root)
    p3 = runner._create_topic_project("coffee", None, root)  # same as p1
    assert p1.dir != p2.dir
    assert p1.dir == p3.dir  # idempotent for the same topic
    assert len(list(root.iterdir())) == 2


def test_batch_no_failures_exits_zero(tmp_path, recorders):
    root = tmp_path / "projects"
    urls = tmp_path / "urls.txt"
    urls.write_text("https://example.com/videos/alpha\n", encoding="utf-8")
    rc = runner.main(["batch", str(urls), "--projects-root", str(root)])
    assert rc == 0  # waiting at gate 1 is a designed stop, not a failure


def test_batch_missing_file_exits_one(tmp_path, capsys):
    rc = runner.main(["batch", str(tmp_path / "nope.txt")])
    assert rc == 1
    assert "not found" in capsys.readouterr().out


# --------------------------------------------------------------------------
# script stage (the real module, not the recorder fake)
# --------------------------------------------------------------------------

def test_script_stage_missing_file_raises_stage_error(tmp_path):
    p = Project(dir=tmp_path)
    with pytest.raises(StageError) as exc_info:
        script_stage.run(p, {}, {})
    assert exc_info.value.stage == "script"
    assert "video-script" in str(exc_info.value)


def test_script_stage_valid_script_passes(tmp_path):
    p = Project(dir=tmp_path)
    p.write_json(contract.SCRIPT, VALID_SCRIPT)
    script_stage.run(p, {}, {})  # no exception
    script_stage.run(p, {}, {}, force=True)  # force changes nothing


def test_script_stage_invalid_script_raises_contract_error(tmp_path):
    p = Project(dir=tmp_path)
    p.write_json(contract.SCRIPT, {"meta": {}, "hook": "", "scenes": []})
    with pytest.raises(ContractError):
        script_stage.run(p, {}, {})


def test_process_surfaces_script_missing_instructions(project, recorders, capsys):
    # Wire the REAL script stage back in: process should fail with the
    # generate-it-in-Claude-Code instruction when script.json is absent.
    sys.modules["pipeline.script"] = script_stage
    rc = runner.main(["process", str(project.dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "script.json not written yet" in out
    assert "video-script" in out


def test_malformed_script_json_is_recorded_not_raised(project, recorders, capsys):
    """Syntactically invalid contracted JSON must surface as a ContractError
    recorded on the status (so batch mode keeps going), never escape as an
    uncaught JSONDecodeError."""
    sys.modules["pipeline.script"] = script_stage
    project.write_text(contract.SCRIPT, "{ this is not valid json")
    rc = runner.main(["process", str(project.dir)])  # must not raise
    assert rc == 1
    out = capsys.readouterr().out
    assert "contract error" in out
    assert "not valid JSON" in out


# --------------------------------------------------------------------------
# stage contract conformance: every stage exposes the frozen signature
# --------------------------------------------------------------------------

def test_all_stage_run_signatures_match_the_frozen_contract():
    import inspect

    for stage, mod in runner.STAGE_MODULES.items():
        module = importlib.import_module(f"pipeline.{mod}")
        params = list(inspect.signature(module.run).parameters.values())
        names = [p.name for p in params]
        assert names == ["project", "cfg", "env", "force"], (
            f"{stage}: run() signature deviates from the stage contract"
        )
        assert params[3].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[3].default is False


def test_cross_stage_file_names_come_from_contract():
    from pipeline import captions, footage, render_ffmpeg, review

    assert captions.CAPTIONS_DIR == contract.CAPTIONS_DIR
    assert captions.MANIFEST == contract.CAPTIONS_MANIFEST
    assert render_ffmpeg.CAPTIONS_DIR == contract.CAPTIONS_DIR
    assert render_ffmpeg.CAPTIONS_MANIFEST == contract.CAPTIONS_MANIFEST
    assert render_ffmpeg.RENDER_REPORT == contract.RENDER_REPORT
    assert footage.FOOTAGE_REPORT == contract.FOOTAGE_REPORT
    assert review.FOOTAGE_REPORT == contract.FOOTAGE_REPORT
    assert review.RENDER_REPORT == contract.RENDER_REPORT


# --------------------------------------------------------------------------
# startup stays instant: importing run.py must not import stage modules
# --------------------------------------------------------------------------

def test_run_import_does_not_load_stage_modules(monkeypatch):
    heavy = ("voice", "footage", "captions", "render_ffmpeg", "review", "publish")
    for mod in heavy:
        monkeypatch.delitem(sys.modules, f"pipeline.{mod}", raising=False)
    importlib.reload(runner)
    for mod in heavy:
        assert f"pipeline.{mod}" not in sys.modules
