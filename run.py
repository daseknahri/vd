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


def cmd_process(args: argparse.Namespace) -> int:
    project = _open_project(args.project_dir)
    if project is None:
        return 1
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
        return 1
    todo = sum(1 for c in checks if c.status == doctor.WARN)
    say(f"result: toolchain OK - {todo} item(s) to configure before going live"
        if todo else "result: all checks passed - ready to make videos")
    return 0


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
        if project.gate_approved(contract.GATE2_APPROVED):
            project.revoke_gate(contract.GATE2_APPROVED)
            say("[gate 2] approval revoked - the re-timed render needs review")
        for stage in ("captions", "render", "review"):
            say(f"[{stage}] running (forced)")
            _load_stage(stage)(project, cfg, env, force=True)
    except (StageError, ContractError) as exc:
        say(f"error: {exc}")
        return 1
    say("repair complete - re-check the contact sheet before approving gate 2:")
    say(f"  {project.path(contract.CONTACT_SHEET)}")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
