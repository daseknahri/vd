"""Video Factory orchestrator: source URL -> reviewed Arabic video.

Commands:
    new       <url> [--slug S]            create a URL-first project folder
    new-topic <topic> [--slug S]          create a topic-first project (no
                                          source video; ingest is skipped)
    process   <project_dir>               run stages, pausing at human gates
    approve   <project_dir> --gate 1|2    record a human gate approval
    redo      <project_dir> --scenes N... re-fetch scene footage, re-render
    batch     <urls.txt>                  process many URLs, summary at end

The two human gates (script read, contact-sheet glance) are never skipped
and never block interactively: when a gate is not yet approved the command
prints instructions and exits 0; re-running `process` resumes after the
gate once it is approved.

Stage modules are imported lazily inside the loop so the CLI starts
instantly. All console output is sanitized to plain ASCII (Windows console
safety) — Arabic lives only in UTF-8 files.
"""

from __future__ import annotations

import argparse
import importlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from pipeline import contract
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

# Stage name -> module under pipeline/. PIPELINE below defines run order.
STAGE_MODULES: dict[str, str] = {
    "ingest": "ingest",
    "script": "script",
    "voice": "voice",
    "footage": "footage",
    "captions": "captions",
    "render": "render_ffmpeg",
    "review": "review",
    "publish": "publish",
}

# ("stage", name) entries run a stage; ("gate", n) entries stop the run
# with instructions unless the human approval marker is on disk.
PIPELINE: list[tuple[str, Any]] = [
    ("stage", "ingest"),
    ("stage", "script"),
    ("gate", 1),
    ("stage", "voice"),
    ("stage", "footage"),
    ("stage", "captions"),
    ("stage", "render"),
    ("stage", "review"),
    ("gate", 2),
    ("stage", "publish"),
]

GATE_MARKERS = {1: contract.GATE1_APPROVED, 2: contract.GATE2_APPROVED}

# Data dependencies: forcing a stage must also re-run every stage that
# consumes its output, or a forced regeneration leaves a stale downstream
# artifact (new voiceover + old captions/render). This is the TRUE dependency
# graph, NOT the linear PIPELINE order — footage consumes script keywords, not
# timing, so forcing `voice` must never re-download clips. Each key lists only
# its DIRECT dependents; `_forced_stages` takes the transitive closure.
STAGE_DEPENDENTS: dict[str, list[str]] = {
    "ingest":   ["script"],   # transcript feeds the (human) script step
    "script":   ["voice", "footage", "captions", "render", "review", "publish"],
    "voice":    ["captions", "render", "review", "publish"],  # voiceover + timing
    "footage":  ["render", "review"],
    "captions": ["render", "review"],
    "render":   ["review"],
    "review":   [],
    "publish":  [],
}


def _forced_stages(force_stage: str | None) -> set[str]:
    """The forced stage plus everything downstream that depends on it
    (transitive closure over STAGE_DEPENDENTS). Empty when nothing is forced."""
    if force_stage is None:
        return set()
    forced = {force_stage}
    stack = [force_stage]
    while stack:
        for dep in STAGE_DEPENDENTS.get(stack.pop(), []):
            if dep not in forced:
                forced.add(dep)
                stack.append(dep)
    return forced


def _effective_pipeline(project: Project) -> list[tuple[str, Any]]:
    """The run order for this project.

    Topic-first projects (topic.txt, no source video) have nothing to
    download or transcribe, so the ingest stage is dropped; the script
    stage then works from topic.txt instead of transcript.txt.
    """
    if project.is_topic_first():
        return [step for step in PIPELINE if step != ("stage", "ingest")]
    return PIPELINE


def say(text: str = "") -> None:
    # Windows consoles mangle non-ASCII (codepage roulette); replace rather
    # than crash. Arabic content is never printed — it stays in files.
    print(text.encode("ascii", "replace").decode("ascii"))


@dataclass
class Status:
    """Outcome of one project's trip through the pipeline."""

    last_completed: str | None = None
    waiting_gate: int | None = None
    error: str | None = None


def _load_stage(stage: str) -> Callable[..., None]:
    mod_name = f"pipeline.{STAGE_MODULES[stage]}"
    try:
        module = importlib.import_module(mod_name)
    except ImportError as exc:
        raise StageError(stage, f"stage module {mod_name} failed to import: {exc}") from exc
    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        raise StageError(stage, f"{mod_name} has no run() function")
    return run_fn


def _gate_instructions(gate: int, project: Project) -> list[str]:
    if gate == 1:
        review_line = f"  read the script:        {project.path(contract.SCRIPT)}"
    else:
        review_line = f"  open the contact sheet: {project.path(contract.CONTACT_SHEET)}"
    return [
        f"GATE {gate}: human approval required - pipeline paused (never skipped).",
        review_line,
        f'  approve with:           python run.py approve "{project.dir}" --gate {gate}',
        f'  then resume:            python run.py process "{project.dir}"',
    ]


def _revoke_downstream_gates(project: Project, stage: str) -> None:
    """Revoke approvals for every gate after `stage` in the pipeline.

    A forced stage regenerates content a human may already have approved;
    keeping the stale marker would let the run sail past the gate with an
    approval that refers to the OLD artifacts (CLAUDE.md rule 2: gates are
    never skipped by any code path).
    """
    seen = False
    for kind, value in PIPELINE:
        if kind == "stage" and value == stage:
            seen = True
        elif kind == "gate" and seen:
            marker = GATE_MARKERS[int(value)]
            if project.gate_approved(marker):
                project.revoke_gate(marker)
                say(f"[gate {value}] approval revoked - '{stage}' is re-run "
                    f"by force; review the new output before approving again")


def _surface_timing_drift(project: Project) -> None:
    """After a real voice run, flag caption-sync risk. Non-fatal — reports
    only. verify_timing is pure (no whisper, no cost); the actual repair is
    the explicit `run.py repair-timing`. We never silently swap ElevenLabs'
    ground-truth timestamps for a whisper guess."""
    if not project.has(contract.TIMING):
        return  # voice hasn't produced timing (e.g. faked in tests) — nothing to check
    align = importlib.import_module("pipeline.align")
    try:
        warnings = align.verify_timing(project)
    except ContractError as exc:
        say(f"[timing] timing.json unreadable: {exc}")
        say(f'[timing] rebuild it with: python run.py repair-timing "{project.dir}"')
        return
    if warnings:
        say(f"[timing] {len(warnings)} drift warning(s) — captions may desync:")
        for w in warnings[:3]:
            say(f"  - {w}")
        if len(warnings) > 3:
            say(f"  ... and {len(warnings) - 3} more")
        say(f'[timing] rebuild from the audio with: python run.py repair-timing "{project.dir}"')


def _rerender_after_voice_change(project: Project, cfg: dict, env: dict) -> None:
    """Re-run the stages that consume the voiceover after it has been rebuilt
    (re-timed or re-voiced). Revokes gate 2 first — the render the human
    approved is being replaced, so it must be reviewed again (CLAUDE.md rule 2).
    Shared by `repair-timing` and the voice-audit auto-heal."""
    if project.gate_approved(contract.GATE2_APPROVED):
        project.revoke_gate(contract.GATE2_APPROVED)
        say("[gate 2] approval revoked - the rebuilt render needs review")
    for stage in ("captions", "render", "review"):
        say(f"[{stage}] running (forced)")
        _load_stage(stage)(project, cfg, env, force=True)


def _report_low_similarity(scene_ids: list[int] | None) -> None:
    if scene_ids:
        say(f"[voice-audit] scene(s) {scene_ids} read differently from the "
            f"script (possible mispronunciation) - see voice_audit_report.json")


def _surface_voice_defects(project: Project, cfg: dict, env: dict) -> None:
    """After a real voice run, free-transcribe the voiceover and catch TTS
    defects that forced alignment hides — chiefly stutters (a word said twice).
    With voice.auto_fix on (default) + a re-rollable provider (chatterbox), a
    stutter is healed and the render rebuilt in place; otherwise it is flagged
    with the explicit fix command. Non-fatal: a missing whisper never fails the
    run. Gate the whole check off with voice.audit: false."""
    vcfg = cfg.get("voice") or {}
    if vcfg.get("audit", True) is False:
        return
    if not (project.has(contract.TIMING) and project.has(contract.VOICEOVER)):
        return  # voice produced no real audio (e.g. faked in tests)
    try:
        vv = importlib.import_module("pipeline.verify_voice")
    except Exception as exc:  # pragma: no cover - import guard
        say(f"[voice-audit] skipped: {exc}")
        return
    provider = str(vcfg.get("provider", "")).strip().lower()
    # Re-rolling ElevenLabs costs money, so only chatterbox auto-heals; for any
    # provider we still audit and flag.
    auto = provider == "chatterbox" and vcfg.get("auto_fix", True) is not False
    try:
        if auto:
            out = vv.fix(project, cfg, env)
            scenes = out.get("healed", {}).get("scenes", [])
            fixed = [s["id"] for s in scenes if s.get("fixed")]
            unfixed = [s["id"] for s in scenes if not s.get("fixed")]
            if out.get("changed"):
                if fixed:
                    say(f"[voice-audit] healed a TTS stutter in scene(s) {fixed} "
                        f"(re-rolled the voice)")
                    _rerender_after_voice_change(project, cfg, env)
                if unfixed:
                    say(f"[voice-audit] scene(s) {unfixed} still stutter after "
                        f"re-rolls - edit the narration or retry: "
                        f'python run.py audit-voice "{project.dir}" --fix')
            _report_low_similarity(out.get("low_similarity"))
        else:
            report = vv.audit(project, cfg)
            if report["repeat_scenes"]:
                say(f"[voice-audit] possible TTS stutter in scene(s) "
                    f"{report['repeat_scenes']} - fix with: "
                    f'python run.py audit-voice "{project.dir}" --fix')
            _report_low_similarity(report["low_similarity_scenes"])
    except (StageError, ContractError) as exc:
        say(f"[voice-audit] skipped: {exc}")
    except Exception as exc:  # noqa: BLE001 - whisper/native failure is non-fatal
        say(f"[voice-audit] skipped (transcription unavailable): {exc}")


def _run_stages(project: Project, force_stage: str | None = None) -> Status:
    """Run the pipeline for one project; stop at unapproved gates.

    Stage/contract failures are recorded on the returned Status (and
    printed) instead of raised, so batch mode can keep going.
    """
    status = Status()
    try:
        cfg = contract.load_config(project.dir)
        env = contract.load_env()
        forced = _forced_stages(force_stage)
        if force_stage is not None:
            _revoke_downstream_gates(project, force_stage)
        for kind, value in _effective_pipeline(project):
            if kind == "gate":
                gate = int(value)
                if not project.gate_approved(GATE_MARKERS[gate]):
                    for line in _gate_instructions(gate, project):
                        say(line)
                    status.waiting_gate = gate
                    return status
                say(f"[gate {gate}] approved - continuing")
                continue
            stage = str(value)
            run_fn = _load_stage(stage)
            say(f"[{stage}] running" + (" (forced)" if stage in forced else ""))
            run_fn(project, cfg, env, force=(stage in forced))
            status.last_completed = stage
            if stage == "voice":
                # Catch (and, for chatterbox, auto-heal) TTS stutters BEFORE the
                # timing check, since a heal rebuilds timing.json.
                _surface_voice_defects(project, cfg, env)
                _surface_timing_drift(project)
        say("all stages complete.")
    except StageError as exc:
        status.error = str(exc)
        say(f"error: {exc}")
    except ContractError as exc:
        status.error = f"contract: {exc}"
        say(f"contract error: {exc}")
    return status


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def _slug_from_url(url: str) -> str:
    """netloc+path (plus query when present, so e.g. watch?v=... URLs stay
    distinct), separators flattened to hyphens by slugify."""
    parts = urlparse(url)
    raw = f"{parts.netloc}{parts.path}" or url
    if parts.query:
        raw += f" {parts.query}"
    return contract.slugify(re.sub(r"[./]+", " ", raw))


def _open_project(path_str: str) -> Project | None:
    path = Path(path_str)
    if not path.is_dir():
        say(f"error: project folder not found: {path}")
        return None
    return Project(dir=path)


def _create_marked_project(marker: str, content: str, slug: str,
                           projects_root: Path | None) -> Project:
    """Create (or reuse) a project folder identified by a marker file.

    slugify truncates to 40 chars, so two DIFFERENT sources can map to the
    same folder name; silently merging them would attribute one source's
    work to the other. Same content -> same folder (idempotent); different
    content -> a numeric suffix keeps the projects distinct.
    """
    base = contract.slugify(slug)
    candidate = base
    n = 2
    while True:
        project = Project.create(candidate, projects_root=projects_root)
        existing = project.path(marker)
        if (existing.exists()
                and existing.read_text(encoding="utf-8").strip() != content.strip()):
            suffix = f"-{n}"
            candidate = base[:40 - len(suffix)] + suffix
            n += 1
            continue
        break
    project.write_text(marker, content + "\n")
    return project


def _create_project(url: str, slug: str | None, projects_root: Path | None) -> Project:
    """Create (or reuse) the URL-first project folder for a source URL."""
    return _create_marked_project(
        contract.SOURCE_URL, url, slug or _slug_from_url(url), projects_root)


def _create_topic_project(topic: str, slug: str | None,
                          projects_root: Path | None) -> Project:
    """Create (or reuse) a topic-first project folder for a bare topic.

    An Arabic topic slugifies to 'untitled' (slugify is ASCII-only), which
    is harmless — the folder name is cosmetic and topic.txt holds the real
    topic — but pass --slug for a readable folder name.
    """
    return _create_marked_project(
        contract.TOPIC, topic, slug or topic, projects_root)


def cmd_new(args: argparse.Namespace) -> int:
    url = args.url.strip()
    if not url:
        say("error: empty URL")
        return 1
    project = _create_project(url, args.slug, args.projects_root)
    say(f"created {project.dir}")
    say(f'next: python run.py process "{project.dir}"')
    return 0


def cmd_new_topic(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if not topic:
        say("error: empty topic")
        return 1
    project = _create_topic_project(topic, args.slug, args.projects_root)
    say(f"created {project.dir} (topic-first: no source video, ingest skipped)")
    say(f'next: python run.py process "{project.dir}"')
    say("      it stops immediately for the script - write it with the")
    say("      video-script skill in Claude Code (it reads topic.txt).")
    return 0


def _project_workflow(project: Project) -> str | None:
    """meta.workflow from script.json ('dub' for dub projects), or None."""
    if not project.has(contract.SCRIPT):
        return None
    try:
        return ((project.script().get("meta") or {}).get("workflow"))
    except ContractError:
        return None


def cmd_process(args: argparse.Namespace) -> int:
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    if _project_workflow(project) == "dub":
        # A dub project keeps the source video (breaks Hard Rule 1 by design);
        # the faceless `process` pipeline does not apply. Redirect, don't run.
        say("this is a DUB project (script.json meta.workflow=dub).")
        say("The faceless 'process' pipeline does not apply here. Drive it with:")
        say(f'  python run.py dub "{project.dir}"   (see DUB.md)')
        return 0
    status = _run_stages(project, force_stage=args.force_stage)
    # Waiting at a gate is a designed stop, not a failure: exit 0.
    return 1 if status.error else 0


def cmd_approve(args: argparse.Namespace) -> int:
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    artifact = contract.SCRIPT if args.gate == 1 else contract.CONTACT_SHEET
    if not project.has(artifact):
        say(f"warning: {artifact} does not exist yet - approving anyway")
    project.approve_gate(GATE_MARKERS[args.gate])
    say(f"gate {args.gate} approved for {project.dir.name}")
    say(f'resume with: python run.py process "{project.dir}"')
    return 0


def cmd_redo(args: argparse.Namespace) -> int:
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    scenes = list(dict.fromkeys(args.scenes))  # de-dupe, keep order
    try:
        cfg = contract.load_config(project.dir)
        env = contract.load_env()
        if project.has(contract.SCRIPT):
            known = {s["id"] for s in project.script()["scenes"]}
            unknown = sorted(set(scenes) - known)
            if unknown:
                say(f"error: scenes not in {contract.SCRIPT}: {unknown}")
                return 1
        deleted: list[str] = []
        for sid in scenes:
            # Same pattern as contract.Project.clip_for_scene.
            for clip in sorted(project.clips_dir.glob(f"scene_{sid:03d}*.mp4")):
                clip.unlink()
                deleted.append(clip.name)
        say(f"deleted {len(deleted)} clip file(s) for scenes {scenes}")
        # The render the human approved is about to be replaced: the gate 2
        # approval no longer refers to anything on disk (CLAUDE.md rule 2 —
        # a stale marker must never let `process` skip the gate).
        if project.gate_approved(contract.GATE2_APPROVED):
            project.revoke_gate(contract.GATE2_APPROVED)
            say("[gate 2] approval revoked - the new render needs a fresh review")
        say(f"[footage] re-fetching scenes {scenes}")
        # footage skips scenes whose clips are on disk, so only the deleted
        # (and any still-missing) scenes are fetched.
        _load_stage("footage")(project, cfg, env, force=False)
        for stage in ("captions", "render", "review"):
            say(f"[{stage}] running (forced)")
            _load_stage(stage)(project, cfg, env, force=True)
    except (StageError, ContractError) as exc:
        say(f"error: {exc}")
        return 1
    say("redo complete - re-check the contact sheet before approving gate 2 again:")
    say(f"  {project.path(contract.CONTACT_SHEET)}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    """Predict ElevenLabs character usage (and $ if a rate is configured)
    for a project's script, BEFORE spending. Reads script.json +
    pronunciation.json only — no network, no API key. Run it at gate 1,
    before approving, to know the cost of the voice stage."""
    from pipeline import voice

    project = _open_project(args.project_dir)
    if project is None:
        return 1
    if not project.has(contract.SCRIPT):
        say(f"error: {contract.SCRIPT} not found — write the script first "
            f"(video-script skill), then estimate")
        return 1
    try:
        script = project.script()
        overrides = project.pronunciation_overrides()
        per_scene = voice.scene_characters(script, overrides)
        cfg = contract.load_config(project.dir)
    except ContractError as exc:
        say(f"contract error: {exc}")
        return 1

    total = sum(chars for _, chars in per_scene)
    say(f"estimate for {project.dir.name}")
    say(f"{'scene':<8}  characters")
    say(f"{'-' * 8}  {'-' * 10}")
    for sid, chars in per_scene:
        say(f"{sid:<8}  {chars}")
    say(f"{'total':<8}  {total}")
    say("(billed = `text` only; previous/next conditioning is not billed)")
    rate = (cfg.get("voice") or {}).get("usd_per_1k_chars")
    if isinstance(rate, (int, float)) and rate > 0:
        say(f"estimated cost: ${total / 1000 * rate:.4f} "
            f"at ${rate}/1k chars (voice.usd_per_1k_chars)")
    else:
        say("set voice.usd_per_1k_chars in config.yaml for a $ estimate")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Preflight: is this checkout ready to make videos? Never hits the
    network. Exit 1 only when a toolchain requirement is broken; missing
    API keys / music are WARNs (legitimately absent before go-live)."""
    from pipeline import doctor

    config_error: str | None = None
    cfg: dict | None = None
    try:
        cfg = contract.load_config(
            Path(args.project_dir) if args.project_dir else None)
    except ContractError as exc:
        config_error = str(exc)
    env = contract.load_env()
    checks = doctor.run_checks(cfg, env, config_error)

    labels = {doctor.OK: "[ OK ]", doctor.WARN: "[WARN]", doctor.FAIL: "[FAIL]"}
    name_w = max(len(c.name) for c in checks)
    say("Video Factory - preflight check")
    for required, header in ((True, "toolchain (required):"),
                             (False, "go-live (before your first real run):")):
        say()
        say(header)
        for c in (c for c in checks if c.required is required):
            say(f"  {labels[c.status]} {c.name:<{name_w}}  {c.detail}")

    say()
    if doctor.has_failures(checks):
        n = sum(1 for c in checks if c.status == doctor.FAIL)
        say(f"result: {n} toolchain check(s) FAILED - fix before running")
        rc = 1
    else:
        todo = sum(1 for c in checks if c.status == doctor.WARN)
        say(f"result: toolchain OK - {todo} item(s) to configure before going live"
            if todo else "result: all checks passed - ready to make videos")
        rc = 0
    _print_dub_readiness(args.project_dir, cfg)
    return rc


def _print_dub_readiness(project_dir: str | None, cfg: dict | None) -> None:
    """When doctor is pointed at a dub project, add a dub-readiness section.
    Informational only (never changes the toolchain exit code)."""
    if not project_dir:
        return
    from pipeline import dub
    p = Project(Path(project_dir))
    is_dub = (_project_workflow(p) == "dub"
              or p.has(dub.SEGMENTS) or p.has(dub.SEGMENTS_REFINED))
    if not is_dub:
        return
    voice_id = str(((cfg or {}).get("voice") or {}).get("voice_id") or "").strip()
    rows = [
        ((p.dir / contract.SOURCE_VIDEO).exists(), "source video present"),
        (bool(voice_id), "voice.voice_id set (project.yaml/config.yaml)"),
        (p.has(dub.SEGMENTS) or p.has(dub.SEGMENTS_REFINED), "segments built"),
        (p.has(dub.TRANSLATIONS), "dub_translations.json present"),
        (p.has(dub.TRANSLATION_APPROVED), "translation approved"),
    ]
    say()
    say("dub readiness (this project):")
    for ok, label in rows:
        say(f"  [{'OK' if ok else '..'}] {label}")


def cmd_repair_timing(args: argparse.Namespace) -> int:
    """Rebuild timing.json from the voiceover audio via local whisper
    alignment (pipeline/align.py), then re-render captions/render/review.

    For when ElevenLabs' per-character timing is bad and captions desync.
    Like `redo`, it revokes gate 2 — the render the human approved is being
    replaced, so it must be reviewed again (CLAUDE.md rule 2)."""
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    align = importlib.import_module("pipeline.align")
    try:
        cfg = contract.load_config(project.dir)
        env = contract.load_env()
        say("[align] rebuilding timing.json from the voiceover (whisper)")
        align.run(project, cfg, env, force=True)
        for w in align.verify_timing(project):
            say(f"[timing] {w}")
        # The re-timed render replaces what the human approved at gate 2.
        _rerender_after_voice_change(project, cfg, env)
    except (StageError, ContractError) as exc:
        say(f"error: {exc}")
        return 1
    say("repair complete - re-check the contact sheet before approving gate 2:")
    say(f"  {project.path(contract.CONTACT_SHEET)}")
    return 0


def cmd_audit_voice(args: argparse.Namespace) -> int:
    """Free-transcribe the voiceover (whisper) and flag TTS stutters (a word
    said twice) + likely mispronunciations that forced alignment hides.

    With --fix, re-roll stuttering scenes until clean, rebuild the voiceover +
    timing, and re-render captions/render/review (revokes gate 2, like
    repair-timing). Without it, only report to voice_audit_report.json."""
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    vv = importlib.import_module("pipeline.verify_voice")
    try:
        cfg = contract.load_config(project.dir)
        env = contract.load_env()
        if args.fix:
            say("[voice-audit] transcribing + healing stutters (whisper)")
            out = vv.fix(project, cfg, env)
            scenes = out.get("healed", {}).get("scenes", [])
            fixed = [s["id"] for s in scenes if s.get("fixed")]
            unfixed = [s["id"] for s in scenes if not s.get("fixed")]
            if not out["before_repeats"]:
                say("[voice-audit] no stutters found - nothing to heal")
            else:
                if fixed:
                    say(f"[voice-audit] healed stutter in scene(s) {fixed}")
                if unfixed:
                    say(f"[voice-audit] scene(s) {unfixed} still stutter after "
                        f"re-rolls - consider editing the narration")
            _report_low_similarity(out.get("low_similarity"))
            if out["changed"]:
                _rerender_after_voice_change(project, cfg, env)
                say("re-check the contact sheet before approving gate 2:")
                say(f"  {project.path(contract.CONTACT_SHEET)}")
        else:
            say("[voice-audit] transcribing (whisper)")
            report = vv.audit(project, cfg)
            say(f"[voice-audit] {len(report['scenes'])} scenes; stutters in "
                f"{report['repeat_scenes'] or 'none'}; low similarity in "
                f"{report['low_similarity_scenes'] or 'none'}")
            say(f"  details: {project.path(vv.VOICE_AUDIT_REPORT)}")
            if report["repeat_scenes"]:
                say(f'fix with: python run.py audit-voice "{project.dir}" --fix')
    except (StageError, ContractError) as exc:
        say(f"error: {exc}")
        return 1
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    urls_file = Path(args.urls_file)
    if not urls_file.is_file():
        say(f"error: URLs file not found: {urls_file}")
        return 1
    urls = [
        line.strip()
        for line in urls_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not urls:
        say(f"error: no URLs in {urls_file}")
        return 1
    results: list[tuple[str, Status]] = []
    for url in urls:
        project = _create_project(url, None, args.projects_root)
        say()
        say(f"--- {project.dir.name} ---")
        # _run_stages records StageError/ContractError on the status
        # instead of raising, so one failing project never stops the rest.
        results.append((project.dir.name, _run_stages(project)))
    _print_summary(results)
    return 1 if any(st.error for _, st in results) else 0


def _print_summary(results: list[tuple[str, Status]]) -> None:
    rows = []
    for name, st in results:
        if st.error:
            note = st.error
        elif st.waiting_gate:
            note = f"waiting at gate {st.waiting_gate}"
        else:
            note = "ok"
        rows.append((name, st.last_completed or "-", note))
    name_w = max(len("project"), *(len(r[0]) for r in rows))
    last_w = max(len("last stage"), *(len(r[1]) for r in rows))
    say()
    say("batch summary:")
    say(f"{'project':<{name_w}}  {'last stage':<{last_w}}  status")
    say(f"{'-' * name_w}  {'-' * last_w}  {'-' * 6}")
    for name, last, note in rows:
        say(f"{name:<{name_w}}  {last:<{last_w}}  {note}")


SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


def _dub_script(slug: str, name: str, *extra: str) -> int:
    """Run one scripts/dub_*.py in a subprocess with the current interpreter
    (the venv Python), so its own guards/idempotency apply. Returns exit code."""
    cmd = [sys.executable, str(SCRIPTS_DIR / name), slug, *extra]
    return subprocess.run(cmd).returncode


def cmd_dub(args: argparse.Namespace) -> int:
    """Advance a DUB project to its next step (see DUB.md). Runs the automatable
    steps (segment, build, captions, voice-after-approval, render) and STOPS with
    instructions at the manual ones (write translations, approve). Never folds
    the dub into `process`; it is a dispatcher over the dub scripts."""
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    from pipeline import dub
    p, slug = project, project.dir.name

    if not (p.dir / contract.SOURCE_VIDEO).exists():
        say(f"[dub] no {contract.SOURCE_VIDEO} in {p.dir} - download the source "
            f"first (see DUB.md 'Downloading the source').")
        return 1
    if not (p.has(dub.SEGMENTS) or p.has(dub.SEGMENTS_REFINED)):
        say("[dub] segmenting source with whisper (a few minutes)...")
        if (rc := _dub_script(slug, "dub_segment.py")):
            return rc
        say(f"[dub] next (manual): if the source has a non-story tail, trim with "
            f'dub_refine_segments.py "{slug}" <first> <last>; then write the Arabic '
            f"translations in projects/{slug}/{dub.TRANSLATIONS}.")
        return 0
    if not p.has(dub.TRANSLATIONS):
        say(f"[dub] write the Arabic translations: projects/{slug}/{dub.TRANSLATIONS}")
        say(f"      (a 'post' block with title/description/hashtags and a "
            f"'source_url' are required).")
        return 0
    if not p.has(contract.SCRIPT):
        say("[dub] building script.json + review page...")
        if (rc := _dub_script(slug, "dub_build_script.py")):
            return rc
        _dub_script(slug, "dub_review.py")  # review page failure is non-fatal
    if not p.has(dub.TRANSLATION_APPROVED):
        say(f"[dub] GATE: review projects/{slug}/dub_review.html, then approve:")
        say(f'      python run.py dub-approve "{p.dir}"')
        return 0
    if not (p.has(contract.VOICEOVER) and p.has(contract.TIMING)):
        say("[dub] generating the Arabic voiceover (ElevenLabs - this spends)...")
        if (rc := _dub_script(slug, "dub_voice.py")):
            return rc
    cap_manifest = f"{contract.CAPTIONS_DIR}/{contract.CAPTIONS_MANIFEST}"
    if not p.has(cap_manifest):
        say("[dub] rendering Arabic captions (Pillow+raqm)...")
        try:
            cfg = contract.load_config(p.dir)
            _load_stage("captions")(p, cfg, contract.load_env(), force=False)
        except (StageError, ContractError) as exc:
            say(f"[dub] captions failed: {exc}")
            return 1
    if not p.has(contract.FINAL):
        say("[dub] final render...")
        if (rc := _dub_script(slug, "dub_render.py")):
            return rc
    say(f"[dub] done: {p.path(contract.FINAL)}")
    return 0


def cmd_dub_approve(args: argparse.Namespace) -> int:
    """Record the human translation-review approval for a dub project. The
    enforced gate: dub_voice.py refuses to spend without this marker."""
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    from pipeline import dub
    if not project.has(contract.SCRIPT):
        say("warning: script.json not built yet - approving translation anyway")
    project.path(dub.TRANSLATION_APPROVED).write_text("approved\n", encoding="utf-8")
    say(f"translation approved for {project.dir.name}")
    say(f'next: python run.py dub "{project.dir}"')
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show where a project stands: which contracted outputs exist, for either
    workflow. Read-only; a fresh session's first orientation command."""
    project = _open_project(args.project_dir)
    if project is None:
        return 1
    from pipeline import dub
    p = project
    is_dub = (_project_workflow(p) == "dub"
              or p.has(dub.SEGMENTS) or p.has(dub.SEGMENTS_REFINED))
    say(f"project: {p.dir.name}")
    if is_dub:
        say("workflow: dub (keeps the source video)")
        seg_name = (dub.SEGMENTS_REFINED if p.has(dub.SEGMENTS_REFINED)
                    else dub.SEGMENTS)
        steps = [
            ("source video", contract.SOURCE_VIDEO),
            ("segments", seg_name),
            ("translations", dub.TRANSLATIONS),
            ("script.json", contract.SCRIPT),
            ("translation approved", dub.TRANSLATION_APPROVED),
            ("voiceover.mp3", contract.VOICEOVER),
            ("timing.json", contract.TIMING),
            ("captions", f"{contract.CAPTIONS_DIR}/{contract.CAPTIONS_MANIFEST}"),
            ("final.mp4", contract.FINAL),
        ]
    else:
        kind = "topic-first" if p.is_topic_first() else "url-first"
        say(f"workflow: faceless ({kind})")
        steps = [
            ("source", contract.TOPIC if p.is_topic_first() else contract.SOURCE_URL),
            ("transcript", contract.TRANSCRIPT),
            ("script.json", contract.SCRIPT),
            ("gate 1 (script)", contract.GATE1_APPROVED),
            ("voiceover.mp3", contract.VOICEOVER),
            ("timing.json", contract.TIMING),
            ("captions", f"{contract.CAPTIONS_DIR}/{contract.CAPTIONS_MANIFEST}"),
            ("final.mp4", contract.FINAL),
            ("gate 2 (review)", contract.GATE2_APPROVED),
            ("post.json", contract.POST),
        ]
    for label, fname in steps:
        say(f"  [{'x' if p.has(fname) else ' '}] {label}")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Video Factory pipeline orchestrator (URL -> final.mp4).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="create a project folder from a source URL")
    p.add_argument("url", help="source video URL (research input only)")
    p.add_argument("--slug", help="project slug (default: derived from the URL)")
    p.add_argument("--projects-root", type=Path, default=None, help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("new-topic",
                       help="create a project from a bare topic (no source video)")
    p.add_argument("topic", help="the video topic (e.g. \"3 facts about the Sahara\")")
    p.add_argument("--slug", help="project slug (recommended for Arabic topics)")
    p.add_argument("--projects-root", type=Path, default=None, help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_new_topic)

    p = sub.add_parser("process", help="run pipeline stages, pausing at human gates")
    p.add_argument("project_dir")
    p.add_argument(
        "--force-stage",
        choices=list(STAGE_MODULES),
        default=None,
        help="re-run this stage AND every stage that depends on its output "
             "(e.g. voice also rebuilds captions/render/review), even if "
             "their outputs exist",
    )
    p.set_defaults(func=cmd_process)

    p = sub.add_parser("approve", help="record a human gate approval")
    p.add_argument("project_dir")
    p.add_argument("--gate", type=int, choices=(1, 2), required=True)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("redo", help="re-fetch footage for scenes, then re-render")
    p.add_argument("project_dir")
    p.add_argument("--scenes", type=int, nargs="+", required=True, metavar="N")
    p.set_defaults(func=cmd_redo)

    p = sub.add_parser("batch", help="process every URL in a file (one per line)")
    p.add_argument("urls_file")
    p.add_argument("--projects-root", type=Path, default=None, help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser(
        "doctor",
        help="check the toolchain + config are ready to make videos")
    p.add_argument("project_dir", nargs="?", default=None,
                   help="optional project folder (applies its project.yaml)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser(
        "estimate",
        help="predict ElevenLabs character usage/cost before running voice")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser(
        "repair-timing",
        help="rebuild timing.json from the voiceover (whisper) and re-render")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_repair_timing)

    p = sub.add_parser(
        "audit-voice",
        help="free-transcribe the voiceover to flag/fix TTS stutters + "
             "mispronunciations")
    p.add_argument("project_dir")
    p.add_argument("--fix", action="store_true",
                   help="re-roll stuttering scenes and re-render (revokes gate 2)")
    p.set_defaults(func=cmd_audit_voice)

    p = sub.add_parser(
        "dub",
        help="advance a dub project to its next step (see DUB.md)")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_dub)

    p = sub.add_parser(
        "dub-approve",
        help="record the dub translation-review approval (gates dub_voice spend)")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_dub_approve)

    p = sub.add_parser(
        "status",
        help="show which outputs exist for a project (either workflow)")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
