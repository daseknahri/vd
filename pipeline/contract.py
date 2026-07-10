"""The data contract between pipeline stages.

Every stage reads and writes files inside a project folder
(projects/YYYY-MM-DD-slug/). This module is the single source of truth for
those file names, the frozen script.json shape, and config/env loading.
Stages import from here and nowhere else, which is what keeps them
independently re-runnable.

Stage I/O (from PLAN.md):
    Ingest   reads source_url.txt           writes transcript.txt
    Script   reads transcript.txt           writes script.json
    Voice    reads script.json              writes voiceover.mp3, timing.json
    Footage  reads script.json              writes clips/*.mp4
    Render   reads all above                writes captions.ass, final.mp4
    Review   reads script.json, clips/      writes contact_sheet.html
    Publish  reads script.json              writes post.json
"""

from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent

# Known-good local installs, newest-preferred. The BtbN build is listed first
# only as a tiebreaker; any ffmpeg >= 6 works for our filtergraphs. NOTE:
# Arabic captions are NEVER burned via libass/subtitles on Windows builds —
# their libass lacks HarfBuzz and mangles modern Arabic fonts (verified
# 2026-06: gyan 8.1.1 and BtbN n8.1 both fail). Captions go through
# pipeline/captions.py (Pillow + libraqm) instead.
_FFMPEG_FALLBACKS = [
    r"C:\Users\user\tools\ffmpeg-btbn\ffmpeg-n8.1-latest-win64-gpl-8.1\bin",
    r"C:\Users\user\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin",
]


def ffmpeg_path(tool: str = "ffmpeg") -> str:
    """Resolve ffmpeg/ffprobe: env override, then PATH, then known installs."""
    env_override = os.environ.get(f"{tool.upper()}_PATH")
    if env_override and Path(env_override).exists():
        return env_override
    found = shutil.which(tool)
    if found:
        return found
    for folder in _FFMPEG_FALLBACKS:
        candidate = Path(folder) / f"{tool}.exe"
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        f"{tool} not found — install it or set {tool.upper()}_PATH"
    )

# Canonical file names inside a project folder. Stages must use these
# constants, never literals, so the contract stays in one place.
SOURCE_URL = "source_url.txt"        # URL-first projects: the research video
TOPIC = "topic.txt"                  # topic-first projects: a bare topic line
SOURCE_VIDEO = "source.mp4"          # research-only; never enters the output
TRANSCRIPT = "transcript.txt"
SCRIPT = "script.json"
VOICEOVER = "voiceover.mp3"
TIMING = "timing.json"
CLIPS_DIR = "clips"
CAPTIONS = "captions.ass"
CAPTIONS_DIR = "captions"             # caption frame PNGs (captions -> render)
CAPTIONS_MANIFEST = "manifest.json"   # inside CAPTIONS_DIR (captions -> render)
CONTACT_SHEET = "contact_sheet.html"
FINAL = "final.mp4"
POST = "post.json"
PRONUNCIATION = "pronunciation.json"  # optional per-project TTS override map
PROJECT_CONFIG = "project.yaml"       # optional per-project config overrides
FOOTAGE_REPORT = "footage_report.json"  # footage -> review
RENDER_REPORT = "render_report.json"    # render -> review
GATE1_APPROVED = ".gate1_script_approved"   # human gate markers
GATE2_APPROVED = ".gate2_review_approved"

VALID_MOODS = {"archival", "energetic", "calm"}


class ContractError(ValueError):
    """A file violates the frozen inter-stage contract."""


# --------------------------------------------------------------------------
# Config / env
# --------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            # Contract violation, not a crash: the orchestrator records it
            # and batch mode keeps going.
            raise ContractError(f"{path.name} is not valid YAML: {exc}") from exc


def load_config(project_dir: Path | None = None) -> dict[str, Any]:
    """Global config.yaml, deep-merged with the project's project.yaml."""
    cfg = _read_yaml(ROOT / "config.yaml")
    if project_dir is not None:
        override_path = Path(project_dir) / PROJECT_CONFIG
        if override_path.exists():
            cfg = _deep_merge(cfg, _read_yaml(override_path))
    return cfg


def load_env() -> dict[str, str]:
    """Keys from .env; missing file -> empty dict (callers decide severity)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return {}
    return {k: v for k, v in dotenv_values(env_path).items() if v}


def require_env(env: dict[str, str], key: str, why: str) -> str:
    value = env.get(key, "")
    if not value:
        raise ContractError(
            f"{key} is not set in .env — required for {why}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


# --------------------------------------------------------------------------
# script.json — the frozen spine
# --------------------------------------------------------------------------

def validate_script(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the frozen script.json shape. Returns data unchanged.

    Shape (PLAN.md section 2):
        meta: { source_url, audience, dialect, target_seconds }
        hook: str
        scenes: [ { id, narration_ar, keywords: [[...], ...],
                    mood, target_seconds } ]
        post: { title, description, hashtags }
    """
    if not isinstance(data, dict):
        raise ContractError("script.json must be a JSON object")

    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise ContractError("script.json: 'meta' object is required")
    for key in ("source_url", "audience", "dialect", "target_seconds"):
        if key not in meta:
            raise ContractError(f"script.json: meta.{key} is required")

    if not isinstance(data.get("hook"), str) or not data["hook"].strip():
        raise ContractError("script.json: non-empty 'hook' string is required")

    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ContractError("script.json: non-empty 'scenes' list is required")
    seen_ids: set[int] = set()
    for i, scene in enumerate(scenes):
        where = f"scenes[{i}]"
        if not isinstance(scene, dict):
            raise ContractError(f"script.json: {where} must be an object")
        sid = scene.get("id")
        if not isinstance(sid, int):
            raise ContractError(f"script.json: {where}.id must be an integer")
        if sid in seen_ids:
            raise ContractError(f"script.json: duplicate scene id {sid}")
        seen_ids.add(sid)
        narration = scene.get("narration_ar")
        if not isinstance(narration, str) or not narration.strip():
            raise ContractError(f"script.json: {where}.narration_ar required")
        kw = scene.get("keywords")
        if (
            not isinstance(kw, list)
            or not kw
            or not all(
                isinstance(s, list) and s and all(isinstance(t, str) for t in s)
                for s in kw
            )
        ):
            raise ContractError(
                f"script.json: {where}.keywords must be a non-empty list of "
                f"non-empty string lists (primary set + fallback sets)"
            )
        if scene.get("mood") not in VALID_MOODS:
            raise ContractError(
                f"script.json: {where}.mood must be one of {sorted(VALID_MOODS)}"
            )
        ts = scene.get("target_seconds")
        if not isinstance(ts, (int, float)) or ts <= 0:
            raise ContractError(f"script.json: {where}.target_seconds must be > 0")

    post = data.get("post")
    if not isinstance(post, dict):
        raise ContractError("script.json: 'post' object is required")
    for key, typ in (("title", str), ("description", str), ("hashtags", list)):
        if not isinstance(post.get(key), typ):
            raise ContractError(f"script.json: post.{key} must be a {typ.__name__}")

    return data


# --------------------------------------------------------------------------
# timing.json — written by Voice, consumed by Render
# --------------------------------------------------------------------------

def validate_timing(data: dict[str, Any]) -> dict[str, Any]:
    """timing.json shape:
        {
          "total_seconds": float,
          "scenes": [ { "id": int, "start": float, "end": float,
                        "words": [ { "word": str, "start": float,
                                     "end": float } ] } ]
        }
    Scene starts/ends are absolute positions in voiceover.mp3, in seconds.
    """
    if not isinstance(data, dict):
        raise ContractError("timing.json must be a JSON object")
    if not isinstance(data.get("total_seconds"), (int, float)):
        raise ContractError("timing.json: 'total_seconds' number required")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ContractError("timing.json: non-empty 'scenes' list required")
    for i, scene in enumerate(scenes):
        where = f"timing scenes[{i}]"
        if not isinstance(scene.get("id"), int):
            raise ContractError(f"{where}.id must be an integer")
        for key in ("start", "end"):
            if not isinstance(scene.get(key), (int, float)):
                raise ContractError(f"{where}.{key} must be a number")
        if scene["end"] <= scene["start"]:
            raise ContractError(f"{where}: end must be > start")
        words = scene.get("words")
        if not isinstance(words, list):
            raise ContractError(f"{where}.words must be a list")
        for w in words:
            if not (
                isinstance(w, dict)
                and isinstance(w.get("word"), str)
                and isinstance(w.get("start"), (int, float))
                and isinstance(w.get("end"), (int, float))
            ):
                raise ContractError(f"{where}.words entries need word/start/end")
    return data


# --------------------------------------------------------------------------
# Project folder
# --------------------------------------------------------------------------

def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


@dataclass
class Project:
    """Handle to one project folder. Cheap to construct; does no I/O."""

    dir: Path

    @classmethod
    def create(cls, slug: str, projects_root: Path | None = None,
               on_date: date | None = None) -> "Project":
        root = projects_root or (ROOT / "projects")
        day = (on_date or date.today()).isoformat()
        project_dir = root / f"{day}-{slugify(slug)}"
        project_dir.mkdir(parents=True, exist_ok=True)
        return cls(dir=project_dir)

    # -- paths ------------------------------------------------------------
    def path(self, name: str) -> Path:
        return self.dir / name

    @property
    def clips_dir(self) -> Path:
        d = self.dir / CLIPS_DIR
        d.mkdir(exist_ok=True)
        return d

    # -- typed accessors ---------------------------------------------------
    def read_text(self, name: str) -> str:
        return self.path(name).read_text(encoding="utf-8")

    def write_text(self, name: str, content: str) -> Path:
        p = self.path(name)
        p.write_text(content, encoding="utf-8")
        return p

    def read_json(self, name: str) -> Any:
        with open(self.path(name), encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as exc:
                # A garbled contracted file is a contract violation, not an
                # uncaught crash: the orchestrator records ContractError on
                # the project status so batch mode keeps going.
                raise ContractError(f"{name} is not valid JSON: {exc}") from exc

    def write_json(self, name: str, data: Any) -> Path:
        p = self.path(name)
        # ensure_ascii=False: Arabic must stay human-readable on disk.
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p

    def script(self) -> dict[str, Any]:
        return validate_script(self.read_json(SCRIPT))

    def timing(self) -> dict[str, Any]:
        return validate_timing(self.read_json(TIMING))

    def pronunciation_overrides(self) -> dict[str, str]:
        """Optional map of written form -> phonetic respelling for TTS."""
        p = self.path(PRONUNCIATION)
        if not p.exists():
            return {}
        data = self.read_json(PRONUNCIATION)
        if not isinstance(data, dict):
            raise ContractError("pronunciation.json must be an object")
        return data

    # -- stage state -------------------------------------------------------
    def has(self, name: str) -> bool:
        return self.path(name).exists()

    def is_topic_first(self) -> bool:
        """True when the project starts from a bare topic (topic.txt) with no
        source video to ingest. URL-first projects (source_url.txt) take
        precedence if somehow both markers exist."""
        return self.has(TOPIC) and not self.has(SOURCE_URL)

    def clips(self) -> list[Path]:
        if not (self.dir / CLIPS_DIR).exists():
            return []
        return sorted((self.dir / CLIPS_DIR).glob("scene_*.mp4"))

    def clip_for_scene(self, scene_id: int) -> Path | None:
        matches = sorted(self.clips_dir.glob(f"scene_{scene_id:03d}*.mp4"))
        return matches[0] if matches else None

    def gate_approved(self, marker: str) -> bool:
        return self.path(marker).exists()

    def approve_gate(self, marker: str) -> None:
        self.path(marker).write_text("approved\n", encoding="utf-8")

    def revoke_gate(self, marker: str) -> None:
        """Remove a gate approval: the approved content no longer exists
        (redo / forced re-run), so the human must review again."""
        self.path(marker).unlink(missing_ok=True)
