"""Video Factory orchestrator: source URL -> reviewed Arabic video.

Commands:
    new      <url> [--slug S]             create a project folder
    process  <project_dir>                run stages, pausing at human gates
    approve  <project_dir> --gate 1|2     record a human gate approval
    redo     <project_dir> --scenes N...  re-fetch scene footage, re-render
    batch    <urls.txt>                   process many URLs, summary at end

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


def _run_stages(project: Project, force_stage: str | None = None) -> Status:
    """Run the pipeline for one project; stop at unapproved gates.

    Stage/contract failures are recorded on the returned Status (and
    printed) instead of raised, so batch mode can keep going.
    """
    status = Status()
    try:
        cfg = contract.load_config(project.dir)
        env = contract.load_env()
        if force_stage is not None:
            _revoke_downstream_gates(project, force_stage)
        for kind, value in PIPELINE:
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
            say(f"[{stage}] running" + (" (forced)" if stage == force_stage else ""))
            run_fn(project, cfg, env, force=(stage == force_stage))
            status.last_completed = stage
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


def _create_project(url: str, slug: str | None, projects_root: Path | None) -> Project:
    """Create (or reuse) the project folder for a URL.

    slugify truncates to 40 chars, so two DIFFERENT URLs can map to the
    same folder name; silently merging them would attribute one URL's
    transcript to the other. Same URL -> same folder (idempotent);
    different URL -> a numeric suffix keeps the projects distinct.
    """
    base = contract.slugify(slug or _slug_from_url(url))
    candidate = base
    n = 2
    while True:
        project = Project.create(candidate, projects_root=projects_root)
        marker = project.path(contract.SOURCE_URL)
        if (marker.exists()
                and marker.read_text(encoding="utf-8").strip() != url):
            suffix = f"-{n}"
            candidate = base[:40 - len(suffix)] + suffix
            n += 1
            continue
        break
    project.write_text(contract.SOURCE_URL, url + "\n")
    return project


def cmd_new(args: argparse.Namespace) -> int:
    url = args.url.strip()
    if not url:
        say("error: empty URL")
        return 1
    project = _create_project(url, args.slug, args.projects_root)
    say(f"created {project.dir}")
    say(f'next: python run.py process "{project.dir}"')
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

    p = sub.add_parser("process", help="run pipeline stages, pausing at human gates")
    p.add_argument("project_dir")
    p.add_argument(
        "--force-stage",
        choices=list(STAGE_MODULES),
        default=None,
        help="re-run this one stage even if its outputs exist",
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
