"""Footage stage: stock-clip search + download (Pexels primary, Pixabay backup).

Reads script.json; writes clips/scene_XXX.mp4 per scene plus
footage_report.json. Maintains the channel-wide used-clip log
(cfg footage.used_clip_log, relative to repo ROOT) so videos never repeat
footage. A scene with no acceptable match is recorded as unmatched in the
report and the stage continues — never silently filled, never raised.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

from pipeline import contract
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

STAGE = "footage"
FOOTAGE_REPORT = contract.FOOTAGE_REPORT  # single source of truth: contract.py

_ATTEMPTS = 3
_TIMEOUT = 30


# --------------------------------------------------------------------------
# HTTP (requests only, timeout=30, 3 attempts with exponential backoff)
# --------------------------------------------------------------------------

def _get_json(url: str, *, params: dict | None = None,
              headers: dict | None = None) -> Any:
    last_err: Exception | None = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        try:
            resp = requests.get(url, params=params, headers=headers,
                                timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as err:
            last_err = err
    raise StageError(STAGE,
                     f"GET {url} failed after {_ATTEMPTS} attempts: {last_err}")


def _download(url: str, dest: Path) -> None:
    last_err: Exception | None = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        tmp = dest.with_suffix(".part")
        try:
            resp = requests.get(url, stream=True, timeout=_TIMEOUT)
            try:
                resp.raise_for_status()
                # Guard against an error page (HTML/JSON) served as HTTP 200 in
                # place of the clip; retry, then fail cleanly rather than saving
                # a "video" that is really an error body.
                ctype = (getattr(resp, "headers", None) or {}).get(
                    "Content-Type", "").lower()
                if ctype.startswith(("text/", "application/json")):
                    raise requests.RequestException(
                        f"expected a video but got Content-Type {ctype!r}")
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
            finally:
                resp.close()
            # write-then-rename so a crash never leaves a half clip that
            # would pass the idempotency check on the next run
            os.replace(tmp, dest)
            return
        except requests.RequestException as err:
            last_err = err
            tmp.unlink(missing_ok=True)
    raise StageError(STAGE,
                     f"download failed after {_ATTEMPTS} attempts: "
                     f"{url}: {last_err}")


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    provider: str
    clip_id: str
    width: int
    height: int
    duration_s: float
    download_url: str


class FootageProvider:
    """Search interface; one implementation per stock-footage service."""

    name: str = ""

    def search(self, query: str, orientation: str, min_height: int,
               min_duration_s: float) -> list[Candidate]:
        raise NotImplementedError


def _matches_orientation(width: int, height: int, orientation: str) -> bool:
    if orientation == "portrait":
        return height > width
    if orientation == "landscape":
        return width > height
    return True


class PexelsProvider(FootageProvider):
    name = "pexels"
    SEARCH_URL = "https://api.pexels.com/videos/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, orientation: str, min_height: int,
               min_duration_s: float) -> list[Candidate]:
        data = _get_json(
            self.SEARCH_URL,
            params={"query": query, "orientation": orientation,
                    "per_page": 15},
            headers={"Authorization": self.api_key},
        )
        out: list[Candidate] = []
        for video in data.get("videos") or []:
            duration = float(video.get("duration") or 0)
            if duration < min_duration_s:
                continue
            files = [
                f for f in video.get("video_files") or []
                if f.get("link")
                and f.get("file_type", "video/mp4") == "video/mp4"
                and (f.get("height") or 0) >= min_height
            ]
            if not files:
                continue
            # smallest file still meeting min_height — never pull 4K
            best = min(files, key=lambda f: (f["height"], f.get("width", 0)))
            width, height = best.get("width") or 0, best["height"]
            if not _matches_orientation(width, height, orientation):
                continue
            out.append(Candidate(self.name, str(video["id"]), width, height,
                                 duration, best["link"]))
        return out


class PixabayProvider(FootageProvider):
    name = "pixabay"
    SEARCH_URL = "https://pixabay.com/api/videos/"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, orientation: str, min_height: int,
               min_duration_s: float) -> list[Candidate]:
        # Pixabay's video API has no orientation param — filtered client-side.
        data = _get_json(
            self.SEARCH_URL,
            params={"key": self.api_key, "q": query, "per_page": 15},
        )
        out: list[Candidate] = []
        for hit in data.get("hits") or []:
            duration = float(hit.get("duration") or 0)
            if duration < min_duration_s:
                continue
            sizes = [
                s for s in (hit.get("videos") or {}).values()
                if isinstance(s, dict) and s.get("url")
                and (s.get("height") or 0) >= min_height
            ]
            if not sizes:
                continue
            best = min(sizes, key=lambda s: (s["height"], s.get("width", 0)))
            width, height = best.get("width") or 0, best["height"]
            if not _matches_orientation(width, height, orientation):
                continue
            out.append(Candidate(self.name, str(hit["id"]), width, height,
                                 duration, best["url"]))
        return out


_PROVIDERS = {
    "pexels": ("PEXELS_API_KEY", PexelsProvider),
    "pixabay": ("PIXABAY_API_KEY", PixabayProvider),
}


def _build_providers(names: list[str],
                     env: dict[str, str]) -> list[FootageProvider]:
    """Providers in cfg order; ones without an API key are dropped.

    No key at all is a ContractError — we never search unauthenticated.
    """
    providers: list[FootageProvider] = []
    needed: list[str] = []
    for name in names:
        if name not in _PROVIDERS:
            raise ContractError(f"footage.providers: unknown provider {name!r}")
        env_key, cls = _PROVIDERS[name]
        needed.append(env_key)
        if env.get(env_key):
            providers.append(cls(env[env_key]))
    if not providers:
        raise ContractError(
            "no footage provider API key set in .env — need at least one of: "
            + ", ".join(needed)
        )
    return providers


# --------------------------------------------------------------------------
# Used-clip log (channel-wide, lives under repo ROOT, keys "provider:id")
# --------------------------------------------------------------------------

def _used_log_path(fcfg: dict) -> Path:
    # pathlib: an absolute cfg value passes through ROOT-joining unchanged
    return contract.ROOT / fcfg.get("used_clip_log", "assets/used_clips.json")


def _load_used_log(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ContractError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{path} must be a JSON object of clip key -> date")
    return data


def _save_used_log(path: Path, log: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2,
                               sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------
# Selection + stage entry point
# --------------------------------------------------------------------------

def _find_candidate(scene: dict, providers: list[FootageProvider],
                    orientation: str, min_height: int, used: dict[str, str],
                    ) -> tuple[Candidate | None, str | None, list[str]]:
    """Keyword sets tried in order; within a set, providers in cfg order.

    First acceptable candidate (filters passed, not in the used-clip log)
    wins. Returns (candidate, query, tried_queries).
    """
    tried: list[str] = []
    for keyword_set in scene["keywords"]:
        query = " ".join(keyword_set)
        tried.append(query)
        for provider in providers:
            try:
                candidates = provider.search(query, orientation, min_height,
                                             scene["target_seconds"])
            except StageError:
                continue  # one provider down must not block the other
            for cand in candidates:
                if f"{cand.provider}:{cand.clip_id}" in used:
                    continue
                return cand, query, tried
    return None, None, tried


def _load_report_entries(project: Project) -> dict[int, dict]:
    """Existing report entries by scene id, so redo runs merge not clobber."""
    if not project.has(FOOTAGE_REPORT):
        return {}
    data = project.read_json(FOOTAGE_REPORT)
    entries: dict[int, dict] = {}
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and isinstance(entry.get("scene"), int):
                entries[entry["scene"]] = entry
    return entries


def run(project: Project, cfg: dict, env: dict, *, force: bool = False) -> None:
    script = project.script()
    fcfg = cfg.get("footage") or {}
    names = fcfg.get("providers") or []
    if not names:
        raise ContractError("config footage.providers must be a non-empty list")

    scenes = script["scenes"]
    # Idempotency (CLAUDE.md rule 5): every scene already has a clip on
    # disk -> nothing to fetch. Return BEFORE demanding an API key or
    # rewriting footage_report.json, so a completed project re-runs fine
    # after a key rotation and the manual-clips workflow (drop files into
    # clips/) reaches the later stages.
    if not force and all(
        project.clip_for_scene(s["id"]) is not None for s in scenes
    ):
        return

    # Generated B-roll (fixed cost) replaces stock search when enabled.
    if fcfg.get("ai_broll"):
        _run_generated(project, scenes, fcfg, force)
        return

    providers = _build_providers(names, env)

    orientation = fcfg.get("orientation") or _orientation_from_aspect(
        (cfg.get("video") or {}).get("aspect_ratio", "9:16"))
    min_height = int(fcfg.get("min_height", 1080))
    log_path = _used_log_path(fcfg)
    used = _load_used_log(log_path)

    entries = _load_report_entries(project)
    for scene in scenes:
        sid = scene["id"]
        if not force and project.clip_for_scene(sid) is not None:
            entries.setdefault(sid, {"scene": sid, "status": "exists"})
            continue
        cand, query, tried = _find_candidate(scene, providers, orientation,
                                             min_height, used)
        if cand is None:
            entries[sid] = {"scene": sid, "status": "unmatched",
                            "tried": tried}
            continue
        _download(cand.download_url, project.clips_dir / f"scene_{sid:03d}.mp4")
        used[f"{cand.provider}:{cand.clip_id}"] = date.today().isoformat()
        _save_used_log(log_path, used)  # per clip: a crash never forgets one
        entries[sid] = {
            "scene": sid,
            "status": "ok",
            "provider": cand.provider,
            "clip_id": cand.clip_id,
            "query": query,
            "width": cand.width,
            "height": cand.height,
            "duration_s": cand.duration_s,
        }

    project.write_json(FOOTAGE_REPORT,
                       [entries[k] for k in sorted(entries)])


def _run_generated(project: Project, scenes: list[dict], fcfg: dict,
                   force: bool) -> None:
    """Generate each scene's clip with ComfyUI + LTX-Video instead of searching
    stock. Per-scene failures are recorded (status "error") and the stage
    continues, so one bad scene never aborts the batch and the human sees it at
    gate 2; flip footage.ai_broll off to fall back to stock. A random per-clip
    seed means `redo` yields a fresh take."""
    from pipeline import broll_comfy  # lazy: optional feature, no hard dependency

    gen = broll_comfy.build(fcfg)
    entries = _load_report_entries(project)
    for scene in scenes:
        sid = scene["id"]
        if not force and project.clip_for_scene(sid) is not None:
            entries.setdefault(sid, {"scene": sid, "status": "exists"})
            continue
        prompt = broll_comfy.prompt_for_scene(scene)
        out = project.clips_dir / f"scene_{sid:03d}.mp4"
        try:
            gen.generate(prompt, out, seed=random.randint(0, 2**31 - 1))
            entries[sid] = {"scene": sid, "status": "generated",
                            "provider": "comfyui-ltxv", "prompt": prompt}
        except StageError as exc:
            entries[sid] = {"scene": sid, "status": "error",
                            "provider": "comfyui-ltxv", "prompt": prompt,
                            "error": str(exc)}
    project.write_json(FOOTAGE_REPORT,
                       [entries[k] for k in sorted(entries)])


def _orientation_from_aspect(aspect_ratio: str) -> str:
    try:
        w, h = (int(x) for x in str(aspect_ratio).split(":"))
    except ValueError:
        raise ContractError(
            f"video.aspect_ratio must look like '9:16', got {aspect_ratio!r}")
    return "portrait" if h > w else "landscape"
