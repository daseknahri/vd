"""Voice-content audit: catch TTS defects that forced alignment cannot.

The voice stage recovers word timing with WhisperX *forced* alignment — it warps
the audio onto the SCRIPT text. So when the model stutters (says a word twice) or
swaps a word, forced alignment maps that onto the script anyway and the defect
ships silently. The first live faceless run hit exactly this: scene 9 said
"...رد فعله تجاهه تجاه" — تجاهه spoken twice — and nothing caught it.

This module transcribes voiceover.mp3 *freely* (faster-whisper, unconstrained by
the script) and compares what was actually said, per scene, to the narration:

- repeat   : a stutter — a word (or its truncated echo, e.g. تجاهه / تجاه) heard
             twice in a row where the script has it once. High confidence, and
             auto-fixable: re-rolling the scene's audio (Chatterbox seed 0 = a
             fresh random take) clears it, and the good take is stored under the
             scene's content-cache key so the voice stage picks it up.
- low similarity : a scene whose heard words diverge grossly from the script
             after Arabic normalization — a likely mispronunciation. Advisory
             (whisper itself mishears Arabic); surfaced for a human, not healed.

Arabic never touches the console: the report (with the heard/repeat text) is a
UTF-8 JSON file; callers print scene ids + numbers only (CLAUDE.md rule 4). The
pure analysis (`analyze`, `find_repeats`, `scene_similarity`) is whisper-free and
directly unit-tested; only `audit`/`fix`/`heal` touch whisper + the GPU provider.
"""

from __future__ import annotations

import difflib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pipeline import contract, wordtiming
from pipeline.contract import ContractError, Project
from pipeline.errors import StageError

STAGE = "voice-audit"
VOICE_AUDIT_REPORT = "voice_audit_report.json"
DEFAULT_MIN_SIMILARITY = 0.55  # below this, a scene is flagged as advisory drift
DEFAULT_TRIES = 4              # re-rolls before giving up on a stuttering scene

normalize = wordtiming.normalize  # Arabic matching form (no tashkeel/tatweel/punct)


# --------------------------------------------------------------------------
# Pure analysis (no whisper, no GPU — unit-tested directly)
# --------------------------------------------------------------------------

def _near_dup(a: str, b: str) -> bool:
    """Two normalized tokens that look like a stutter: identical, or the shorter
    is a 3+char prefix of the longer with only a small tail (catches the common
    truncated echo تجاه / تجاهه). Deliberately tight — no fuzzy edit distance —
    so real, distinct consecutive words are not mistaken for a repeat."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and long.startswith(short) and len(long) - len(short) <= 3


def find_repeats(script_tokens: list[str], heard_tokens: list[str]) -> list[str]:
    """Consecutive near-duplicate heard words that the script does NOT repeat —
    i.e. TTS stutters. Returns the offending heard bigrams (original spelling,
    for the report)."""
    sn = [normalize(t) for t in script_tokens]
    hn = [normalize(t) for t in heard_tokens]
    legit = {(sn[i], sn[i + 1]) for i in range(len(sn) - 1)
             if _near_dup(sn[i], sn[i + 1])}
    out: list[str] = []
    for i in range(len(hn) - 1):
        a, b = hn[i], hn[i + 1]
        if _near_dup(a, b) and (a, b) not in legit:
            out.append(f"{heard_tokens[i]} {heard_tokens[i + 1]}")
    return out


def scene_similarity(script_tokens: list[str], heard_tokens: list[str]) -> float:
    """difflib ratio of the two normalized token streams (1.0 = identical)."""
    a = [normalize(t) for t in script_tokens]
    b = [normalize(t) for t in heard_tokens]
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def bucket_by_scene(
    timing: dict[str, Any], heard_timed: list[dict[str, Any]]
) -> dict[int, list[str]]:
    """Assign each freely-heard word to the timing scene whose [start, end)
    contains its midpoint; stragglers go to the nearest scene by edge distance."""
    scenes = sorted(timing["scenes"], key=lambda s: s["start"])
    out: dict[int, list[str]] = {s["id"]: [] for s in scenes}
    if not scenes:
        return out
    for w in heard_timed:
        mid = (float(w["start"]) + float(w["end"])) / 2.0
        placed = False
        for s in scenes:
            if s["start"] <= mid < s["end"]:
                out[s["id"]].append(w["word"])
                placed = True
                break
        if not placed:
            nearest = min(
                scenes,
                key=lambda s: min(abs(mid - s["start"]), abs(mid - s["end"])),
            )
            out[nearest["id"]].append(w["word"])
    return out


def analyze(
    script: dict[str, Any], timing: dict[str, Any],
    heard_timed: list[dict[str, Any]], *,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> dict[str, Any]:
    """Per-scene report from a free transcription. Pure; no I/O."""
    heard_by_scene = bucket_by_scene(timing, heard_timed)
    scenes_out: list[dict[str, Any]] = []
    repeat_ids: list[int] = []
    low_ids: list[int] = []
    for s in script["scenes"]:
        sid = s["id"]
        stoks = s["narration_ar"].split()
        htoks = heard_by_scene.get(sid, [])
        reps = find_repeats(stoks, htoks)
        sim = scene_similarity(stoks, htoks)
        if reps:
            repeat_ids.append(sid)
        if sim < min_similarity:
            low_ids.append(sid)
        scenes_out.append({
            "id": sid, "similarity": round(sim, 3), "repeats": reps,
            "script_wc": len(stoks), "heard_wc": len(htoks),
            "heard": " ".join(htoks),
        })
    return {
        "min_similarity": min_similarity,
        "scenes": scenes_out,
        "repeat_scenes": repeat_ids,
        "low_similarity_scenes": low_ids,
        "ok": not repeat_ids and not low_ids,
    }


# --------------------------------------------------------------------------
# Whisper (free transcription) — patched out in tests
# --------------------------------------------------------------------------

def _load_whisper(cfg: dict) -> Any:
    tcfg = cfg.get("transcribe") or {}
    from faster_whisper import WhisperModel  # heavy native import; lazy
    try:
        return WhisperModel(
            tcfg.get("model", "small"),
            device=tcfg.get("device", "cpu"),
            compute_type=tcfg.get("compute_type", "int8"),
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as a stage failure
        raise StageError(STAGE, f"could not load faster-whisper: {exc}") from exc


def _transcribe_timed(model: Any, audio: Path) -> list[dict[str, Any]]:
    try:
        segments, _info = model.transcribe(
            str(audio), word_timestamps=True, language="ar"
        )
        return [
            {"word": w.word, "start": float(w.start), "end": float(w.end)}
            for segment in segments for w in (segment.words or [])
        ]
    except Exception as exc:  # noqa: BLE001
        raise StageError(STAGE, f"free transcription failed: {exc}") from exc


def _transcribe_words_from_bytes(model: Any, audio: bytes) -> list[str]:
    """Free-transcribe one in-memory scene take -> heard word strings."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        tmp.write(audio)
        tmp.close()
        return [w["word"] for w in _transcribe_timed(model, Path(tmp.name))]
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Audit + heal (I/O)
# --------------------------------------------------------------------------

def audit(project: Project, cfg: dict, *, model: Any = None,
          write: bool = True) -> dict[str, Any]:
    """Free-transcribe voiceover.mp3 and report per-scene stutters + drift.
    Writes voice_audit_report.json unless write=False."""
    script = project.script()
    timing = project.timing()
    audio = project.path(contract.VOICEOVER)
    if not audio.exists():
        raise ContractError(
            f"{contract.VOICEOVER} not found in {project.dir} — run voice first"
        )
    heard = _transcribe_timed(model or _load_whisper(cfg), audio)
    report = analyze(script, timing, heard)
    if write:
        project.write_json(VOICE_AUDIT_REPORT, report)
    return report


def _write_cache(cache_dir: Path, key: str, audio: bytes,
                 alignment: dict[str, Any]) -> None:
    (cache_dir / f"{key}.mp3").write_bytes(audio)
    (cache_dir / f"{key}.json").write_text(
        json.dumps(alignment, ensure_ascii=False), encoding="utf-8")


def heal(project: Project, cfg: dict, env: dict, scene_ids: list[int], *,
         tries: int = DEFAULT_TRIES, model: Any = None) -> dict[str, Any]:
    """Re-roll each stuttering scene's cached audio until the repeat is gone.

    A fresh take differs because the Chatterbox seed is 0 (random); when the seed
    is pinned we vary it per attempt. The good take is written under the scene's
    existing content-cache key, so a subsequent voice.run(force=True) rebuilds
    voiceover.mp3 + timing.json from it with no new synthesis for other scenes.
    Does NOT rebuild — the caller (`fix`) does that once, at the end."""
    from pipeline import voice

    script = project.script()
    scenes = script["scenes"]
    index_of = {s["id"]: i for i, s in enumerate(scenes)}
    overrides = project.pronunciation_overrides()
    spoken = [voice.spoken_text(s["narration_ar"].strip(), overrides) for s in scenes]
    delivery_cfg = (cfg.get("voice") or {}).get("delivery")

    cache_dir = project.path(voice.CACHE_DIR)
    cache_dir.mkdir(exist_ok=True)
    provider = voice.build_provider(cfg, env)
    signature = provider.signature()
    cfg_seed = int(getattr(provider, "seed", 0) or 0)
    model = model or _load_whisper(cfg)

    results: list[dict[str, Any]] = []
    try:
        for sid in scene_ids:
            i = index_of.get(sid)
            if i is None:
                continue
            prev = spoken[i - 1] if i > 0 else ""
            nxt = spoken[i + 1] if i < len(scenes) - 1 else ""
            next_mood = scenes[i + 1].get("mood") if i < len(scenes) - 1 else None
            style, _pause = voice.delivery_for_scene(scenes[i], next_mood, delivery_cfg)
            key = voice.cache_key(signature, spoken[i], prev, nxt, style)
            script_tokens = scenes[i]["narration_ar"].split()

            fixed = False
            attempts = 0
            error = None
            for k in range(max(1, tries)):
                attempts += 1
                # seed 0 config -> keep 0 (random each call); pinned seed -> vary
                # it so a re-roll actually differs.
                trial = 0 if cfg_seed == 0 else cfg_seed + 1 + k
                had_seed = hasattr(provider, "seed")
                if had_seed:
                    provider.seed = trial
                try:
                    audio, alignment = provider.synthesize(
                        spoken[i], prev, nxt, style=style)
                except StageError as exc:
                    error = str(exc)
                    break
                finally:
                    if had_seed:
                        provider.seed = cfg_seed
                # Always keep the latest take (so we never leave the scene without
                # audio), then decide whether it is clean.
                _write_cache(cache_dir, key, audio, alignment)
                if not find_repeats(script_tokens,
                                    _transcribe_words_from_bytes(model, audio)):
                    fixed = True
                    break
            results.append({"id": sid, "fixed": fixed, "attempts": attempts,
                            "error": error})
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    return {"scenes": results,
            "all_fixed": all(r["fixed"] for r in results) if results else True}


def fix(project: Project, cfg: dict, env: dict, *,
        tries: int = DEFAULT_TRIES, model: Any = None) -> dict[str, Any]:
    """Audit, heal any stuttering scenes, rebuild the voiceover + timing, re-audit.

    Returns a flat summary (scene-id lists + per-scene heal outcomes) so callers
    can report in ASCII. Rebuilds voiceover.mp3/timing.json via voice.run when a
    heal happened; the caller re-renders captions/render/review."""
    from pipeline import voice

    model = model or _load_whisper(cfg)
    before = audit(project, cfg, model=model, write=False)
    healed: dict[str, Any] = {"scenes": [], "all_fixed": True}
    changed = bool(before["repeat_scenes"])
    if changed:
        healed = heal(project, cfg, env, before["repeat_scenes"],
                      tries=tries, model=model)
        voice.run(project, cfg, env, force=True)  # rebuild from the healed cache
    after = audit(project, cfg, model=model, write=True)
    return {
        "changed": changed,
        "before_repeats": before["repeat_scenes"],
        "after_repeats": after["repeat_scenes"],
        "healed": healed,
        "low_similarity": after["low_similarity_scenes"],
    }
