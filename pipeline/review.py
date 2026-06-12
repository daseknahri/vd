"""Review stage: script.json + clips/ + stage reports -> contact_sheet.html.

Human gate 2. One self-contained RTL HTML page (inline CSS, no JS) with a
clip-midpoint thumbnail, the narration, keyword sets and target-vs-actual
timing per scene, so a human can glance at visual match quality. Scenes the
footage/render stages reported as unmatched or placeholder — and scenes
with no clip on disk at all — carry a loud FLAGGED badge.
"""

from __future__ import annotations

import html
import subprocess
from pathlib import Path
from typing import Any

from pipeline import contract
from pipeline.contract import ContractError, ffmpeg_path
from pipeline.errors import StageError

STAGE = "review"

# Cross-stage report names come from contract.py (single source of truth).
FOOTAGE_REPORT = contract.FOOTAGE_REPORT
RENDER_REPORT = contract.RENDER_REPORT

THUMBS_DIR = "thumbs"  # sits next to captions/ inside the project folder
THUMB_WIDTH = 320

_FLAG_STATUSES = {"flagged", "unmatched", "placeholder", "gap", "missing",
                  "failed"}


# --------------------------------------------------------------------------
# Stage entry point
# --------------------------------------------------------------------------

def run(project: contract.Project, cfg: dict, env: dict, *,
        force: bool = False) -> None:
    if not force and project.has(contract.CONTACT_SHEET):
        return
    if not project.has(contract.SCRIPT):
        # Missing contracted input = contract violation (consistent with
        # ingest/render).
        raise ContractError(
            f"{contract.SCRIPT} not found — run the script stage first"
        )
    script = project.script()
    actual = _actual_seconds_by_scene(project)
    flagged = _flagged_scenes(project)

    cards: list[str] = []
    flagged_ids: set[int] = set()
    for scene in script["scenes"]:
        sid = scene["id"]
        clip = project.clip_for_scene(sid)
        reasons: list[str] = []
        if sid in flagged:
            reasons.append(flagged[sid])
        if clip is None:
            reasons.append("no clip in clips/ for this scene")
        if reasons:
            flagged_ids.add(sid)
        thumb_rel = (_make_thumbnail(project, sid, clip, force=force)
                     if clip is not None else None)
        cards.append(_scene_card(scene, thumb_rel, actual.get(sid), reasons))

    page = _render_page(project.dir, script, cards, flagged_ids)
    project.write_text(contract.CONTACT_SHEET, page)


# --------------------------------------------------------------------------
# Inputs: timing + stage reports
# --------------------------------------------------------------------------

def _actual_seconds_by_scene(project: contract.Project) -> dict[int, float]:
    if not project.has(contract.TIMING):
        return {}
    timing = project.timing()
    return {s["id"]: round(s["end"] - s["start"], 1) for s in timing["scenes"]}


def _flagged_scenes(project: contract.Project) -> dict[int, str]:
    """Scene id -> human-readable reason, from any stage report present."""
    flagged: dict[int, str] = {}
    for name in (FOOTAGE_REPORT, RENDER_REPORT):
        if not project.has(name):
            continue
        # A garbled report raises ContractError from Project.read_json —
        # the orchestrator records it and batch mode keeps going.
        flagged.update(_flagged_in_report(project.read_json(name), name))
    return flagged


def _flagged_in_report(data: Any, source: str) -> dict[int, str]:
    """Tolerant reader: reports may list flags explicitly ('flagged',
    'gaps', ...) or per-scene via a flagged/placeholder/status field."""
    explicit: list[Any] = []
    scenes: list[Any] = []
    if isinstance(data, dict):
        for key in ("flagged", "flagged_scenes", "gaps", "unmatched"):
            value = data.get(key)
            if isinstance(value, list):
                explicit.extend(value)
        if isinstance(data.get("scenes"), list):
            scenes = data["scenes"]
    elif isinstance(data, list):
        scenes = data

    out: dict[int, str] = {}
    for entry in explicit:
        sid = _scene_id_of(entry)
        if sid is not None:
            out[sid] = _entry_reason(entry, source)
    for entry in scenes:
        if _is_flagged_entry(entry):
            sid = _scene_id_of(entry)
            if sid is not None:
                out[sid] = _entry_reason(entry, source)
    return out


def _scene_id_of(entry: Any) -> int | None:
    if isinstance(entry, int):
        return entry
    if isinstance(entry, dict):
        for key in ("id", "scene_id", "scene"):
            if isinstance(entry.get(key), int):
                return entry[key]
    return None


def _is_flagged_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("flagged") or entry.get("placeholder"):
        return True
    return str(entry.get("status", "")).lower() in _FLAG_STATUSES


def _entry_reason(entry: Any, source: str) -> str:
    if isinstance(entry, dict):
        for key in ("reason", "message", "note", "status"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return f"{source}: {value.strip()}"
    return f"{source}: flagged"


# --------------------------------------------------------------------------
# Thumbnails (ffmpeg, clip midpoint)
# --------------------------------------------------------------------------

def _probe_duration(path: Path) -> float:
    cmd = [
        ffmpeg_path("ffprobe"), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    # Explicit encoding: Windows locale codepages choke (strict
    # UnicodeDecodeError) on UTF-8 bytes in ffprobe output.
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise StageError(STAGE, f"ffprobe failed on {path.name}: "
                                f"{proc.stderr.strip()[:300]}")
    try:
        duration = float(proc.stdout.strip())
    except ValueError:
        raise StageError(STAGE, f"ffprobe gave no duration for {path.name}")
    if duration <= 0:
        raise StageError(STAGE, f"{path.name} has zero duration")
    return duration


def _make_thumbnail(project: contract.Project, scene_id: int, clip: Path, *,
                    force: bool) -> str:
    """Extract a midpoint frame to thumbs/scene_XXX.jpg; return relative path."""
    thumbs = project.path(THUMBS_DIR)
    thumbs.mkdir(exist_ok=True)
    out = thumbs / f"scene_{scene_id:03d}.jpg"
    rel = f"{THUMBS_DIR}/{out.name}"
    if out.exists() and not force:
        return rel
    midpoint = _probe_duration(clip) / 2
    cmd = [
        ffmpeg_path("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{midpoint:.3f}", "-i", str(clip),
        "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "3",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out.exists():
        raise StageError(STAGE, f"thumbnail extraction failed for "
                                f"{clip.name}: {proc.stderr.strip()[:300]}")
    return rel


# --------------------------------------------------------------------------
# HTML (self-contained, RTL, dark, no JS)
# --------------------------------------------------------------------------

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: #14171c; color: #e8eaed;
       font-family: "Tajawal", "Segoe UI", Tahoma, sans-serif; }
header h1 { margin: 0 0 6px; font-size: 24px; }
.hook { font-size: 18px; color: #c7cdd4; margin: 0 0 4px; }
.summary { color: #9aa0a6; font-size: 13px; margin: 0 0 20px; }
.grid { display: grid; gap: 16px;
        grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
.card { position: relative; background: #1c2128; border: 1px solid #2a313a;
        border-radius: 10px; padding: 14px; }
.card.flagged { border-color: #e05252; box-shadow: 0 0 0 2px #e0525266; }
.badge { position: absolute; top: 10px; left: 10px; z-index: 1;
         background: #e05252; color: #fff; font-weight: 700; font-size: 13px;
         letter-spacing: 1px; padding: 4px 10px; border-radius: 6px; }
.scene-no { color: #9aa0a6; font-size: 13px; margin-bottom: 8px; }
.thumb { display: block; width: 320px; max-width: 100%; margin: 0 auto 10px;
         border-radius: 6px; background: #000; }
.no-thumb { display: flex; align-items: center; justify-content: center;
            height: 180px; margin-bottom: 10px; border-radius: 6px;
            border: 1px dashed #4a5360; color: #9aa0a6; font-size: 13px; }
.narration { font-size: 17px; line-height: 1.8; margin: 0 0 10px; }
.kwsets { direction: ltr; text-align: left; margin-bottom: 10px; }
.kwset { margin-bottom: 4px; }
.kwlabel { color: #7aa2f7; font-size: 11px; text-transform: uppercase;
           letter-spacing: 1px; margin-right: 6px; }
.chip { display: inline-block; background: #2a313a; color: #bdc3c9;
        border-radius: 999px; padding: 2px 10px; margin: 2px;
        font-size: 12px; }
.timing { color: #9aa0a6; font-size: 13px; }
.reason { color: #e08585; font-size: 13px; margin-top: 6px; }
footer { margin-top: 28px; padding-top: 16px; border-top: 1px solid #2a313a;
         color: #9aa0a6; font-size: 14px; line-height: 2; }
code { direction: ltr; unicode-bidi: embed; display: inline-block;
       background: #1c2128; border: 1px solid #2a313a; border-radius: 6px;
       padding: 2px 10px; color: #8fd4a8; }
"""


def _keyword_sets(keywords: list[list[str]]) -> str:
    rows = []
    for i, kwset in enumerate(keywords):
        label = "primary" if i == 0 else f"fallback {i}"
        chips = "".join(f'<span class="chip">{html.escape(k)}</span>'
                        for k in kwset)
        rows.append(f'<div class="kwset"><span class="kwlabel">{label}'
                    f'</span>{chips}</div>')
    return "".join(rows)


def _scene_card(scene: dict, thumb_rel: str | None,
                actual_seconds: float | None, reasons: list[str]) -> str:
    sid = scene["id"]
    badge = '<div class="badge">FLAGGED</div>' if reasons else ""
    if thumb_rel:
        visual = (f'<img class="thumb" src="{html.escape(thumb_rel)}" '
                  f'alt="scene {sid} thumbnail">')
    else:
        visual = '<div class="no-thumb">no clip on disk</div>'
    actual = f"{actual_seconds:.1f}s" if actual_seconds is not None else "—"
    reason_html = "".join(f'<div class="reason">{html.escape(r)}</div>'
                          for r in reasons)
    css_class = "card flagged" if reasons else "card"
    return (
        f'<article class="{css_class}">\n'
        f"{badge}\n"
        f'<div class="scene-no">scene {sid} · '
        f'{html.escape(str(scene["mood"]))}</div>\n'
        f"{visual}\n"
        f'<p class="narration">{html.escape(scene["narration_ar"])}</p>\n'
        f'<div class="kwsets">{_keyword_sets(scene["keywords"])}</div>\n'
        f'<div class="timing">target {scene["target_seconds"]}s · '
        f"actual {actual}</div>\n"
        f"{reason_html}\n"
        f"</article>"
    )


def _render_page(project_dir: Path, script: dict, cards: list[str],
                 flagged_ids: set[int]) -> str:
    name = html.escape(project_dir.name)
    # Footer commands must be runnable as printed from the repo root, so
    # they carry the full quoted project path (same form run.py prints),
    # not the bare folder name.
    redo_target = html.escape(f'"{project_dir}"')
    meta = script["meta"]
    redo_ids = " ".join(str(i) for i in sorted(flagged_ids)) or "3 5"
    summary = (f"{len(script['scenes'])} scenes · target "
               f"{html.escape(str(meta['target_seconds']))}s · dialect "
               f"{html.escape(str(meta['dialect']))}")
    cards_html = "\n".join(cards)
    return (
        "<!DOCTYPE html>\n"
        '<html dir="rtl" lang="ar">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>Contact sheet — {name}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        "<header>\n"
        f"<h1>Contact sheet — {name}</h1>\n"
        f'<p class="hook">{html.escape(script["hook"])}</p>\n'
        f'<p class="summary">{summary}</p>\n'
        "</header>\n"
        f'<main class="grid">\n{cards_html}\n</main>\n'
        "<footer>\n"
        "<p>Redo scenes (re-fetch footage + re-render only those): "
        f"<code>python run.py redo {redo_target} --scenes {redo_ids}</code></p>\n"
        "<p>Approve gate 2 when every scene looks right: "
        f"<code>python run.py approve {redo_target} --gate 2</code></p>\n"
        "</footer>\n"
        "</body>\n"
        "</html>\n"
    )
