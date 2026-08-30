"""Dub workflow — pure, tested logic shared by scripts/dub_*.py and run.py.

The dub path keeps the SOURCE video's picture, mutes its audio, lays an Arabic
ElevenLabs voiceover on top, and burns Arabic RTL captions (see DUB.md). It is
deliberately separate from the faceless `run.py process` pipeline and breaks
Hard Rule 1 by design — but it reuses the spine: it emits contract-valid
script.json / timing.json, so pipeline.captions and render_ffmpeg's caption
builder work unchanged (Hard Rule 3 holds — Arabic only through Pillow+raqm).

This module holds the pure, unit-testable functions. The thin scripts/dub_*.py
own I/O + ffmpeg/whisper side effects and delegate their logic here; tests call
these functions directly with fixtures. File names are contract constants; the
voice/render helpers are imported by their public aliases (never the private
underscore names).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline import contract
from pipeline.contract import ContractError

# Public re-exports so the dub scripts never reach into private internals.
from pipeline.voice import (  # noqa: F401
    build_provider, synthesize_cached, probe_duration, words_from_alignment,
    VOICE_REPORT,
)
from pipeline.render_ffmpeg import (  # noqa: F401
    load_manifest, build_caption_track, probe,
)

# --- dub project file names (kept here so no script hardcodes literals) ---
SEGMENTS = "dub_segments.json"              # raw whisper output (dub_segment)
SEGMENTS_REFINED = "dub_segments.refined.json"  # merged sentences (refine)
TRANSLATIONS = "dub_translations.json"      # hand-authored Arabic + post meta
TRANSLATION_APPROVED = ".dub_translation_approved"  # human gate marker

# --- tunables (overridable per project via project.yaml dub.*) ---
DEFAULT_STORY_END_MARKER = "now lets do some shadowing"
MAX_SENTENCE_S = 7.0     # force a caption split past this many spoken seconds
MAX_SPEED = 1.30         # never atempo a clip faster than this to fit its slot
MIN_GAP = 0.05           # a slot smaller than this is treated as unusable


# ==========================================================================
# Segmentation (dub_segment) — story-boundary + sentence grouping
# ==========================================================================

def norm_word(word: str) -> str:
    """Lowercase, keep only alphanumerics. Drops apostrophes so contractions
    match a marker ("let's" -> "lets", so a marker written "now lets ..."
    matches the whisper token stream regardless of apostrophe rendering)."""
    return "".join(c for c in word.lower() if c.isalnum())


def find_story_end(norm_words: list[str], marker: str) -> int:
    """Index in the word stream where the marker phrase begins, or
    len(norm_words) if it never matches. Marker is normalized the same way."""
    tokens = [t for t in (norm_word(t) for t in marker.split()) if t]
    if not tokens:
        return len(norm_words)
    n = len(tokens)
    for i in range(len(norm_words) - n + 1):
        if norm_words[i:i + n] == tokens:
            return i
    return len(norm_words)


def group_sentences(story_words: list[dict], max_s: float) -> list[dict]:
    """Group a word stream (dicts with t/start/end) into caption-sized
    sentences: break after .?! or once a sentence exceeds max_s seconds."""
    segs: list[dict] = []
    cur: list[dict] = []
    if not story_words:
        return segs
    cur_start = story_words[0]["start"]
    for w in story_words:
        cur.append(w)
        ends_sentence = w["t"].rstrip()[-1:] in ".?!"
        too_long = (w["end"] - cur_start) >= max_s
        if ends_sentence or too_long:
            segs.append(_sentence(segs, cur_start, w["end"], cur))
            cur = []
            if w is not story_words[-1]:
                cur_start = w["end"]
    if cur:
        segs.append(_sentence(segs, cur_start, cur[-1]["end"], cur))
    return segs


def _sentence(existing: list[dict], start: float, end: float,
              words: list[dict]) -> dict:
    return {
        "id": len(existing) + 1,
        "start": round(start, 3),
        "end": round(end, 3),
        "en": " ".join(x["t"] for x in words).strip(),
    }


def build_segments(words: list[dict], marker: str, max_s: float,
                   language_probability: float = 0.0) -> dict:
    """Full segmentation output from a whisper word stream. Reports whether the
    story-end marker matched so the caller can warn loudly on a fresh source."""
    norm = [norm_word(w["t"]) for w in words]
    end_idx = find_story_end(norm, marker)
    story = words[:end_idx]
    if not story:
        raise ContractError("dub segmentation: empty story window")
    return {
        "story_start": round(story[0]["start"], 3),
        "story_end": round(story[-1]["end"], 3),
        "language_probability": round(float(language_probability), 3),
        "marker_found": end_idx < len(words),
        "segments": group_sentences(story, max_s),
    }


# ==========================================================================
# Refine (dub_refine_segments) — merge fragments into whole sentences
# ==========================================================================

def refine_segments(raw: dict, first_id: int, last_id: int) -> dict:
    """Merge the whisper fragments in id-range [first_id..last_id] into whole
    sentences (break on .?!), preserving first.start / last.end. Non-destructive:
    the caller writes this to SEGMENTS_REFINED, leaving raw SEGMENTS intact."""
    segments = raw.get("segments")
    if not isinstance(segments, list):
        raise ContractError(f"{SEGMENTS}: 'segments' list is required")
    kept = [s for s in segments if first_id <= s["id"] <= last_id]
    if not kept:
        ids = [s["id"] for s in segments]
        span = f"{min(ids)}..{max(ids)}" if ids else "none"
        raise ContractError(
            f"refine: no segments in id range [{first_id}..{last_id}]; "
            f"{SEGMENTS} has ids {span}")

    merged: list[dict] = []
    buf: list[dict] = []
    for s in kept:
        buf.append(s)
        if s["en"].rstrip()[-1:] in ".?!":
            merged.append(_merge(buf, len(merged) + 1))
            buf = []
    if buf:
        merged.append(_merge(buf, len(merged) + 1))
    return {
        "source": "whisper timing scaffolding (English never enters output)",
        "story_start": merged[0]["start"],
        "story_end": merged[-1]["end"],
        "boundary_ids": [first_id, last_id],
        "segments": merged,
    }


def _merge(buf: list[dict], new_id: int) -> dict:
    return {
        "id": new_id,
        "start": buf[0]["start"],
        "end": buf[-1]["end"],
        "en": " ".join(x["en"].strip() for x in buf).strip(),
    }


def load_segments(project: contract.Project) -> dict:
    """Prefer the refined sentences; fall back to the raw whisper output.
    Raises a clean ContractError (not a traceback) when neither exists."""
    if project.has(SEGMENTS_REFINED):
        return project.read_json(SEGMENTS_REFINED)
    if project.has(SEGMENTS):
        return project.read_json(SEGMENTS)
    raise ContractError(
        f"no dub segments found — run dub_segment.py then "
        f"dub_refine_segments.py (looked for {SEGMENTS_REFINED} / {SEGMENTS})")


# ==========================================================================
# Build script.json (dub_build_script) — translation -> contract-valid script
# ==========================================================================

def build_script(segs: dict, translations: dict, source_url: str) -> dict:
    """segs (+ per-id Arabic in translations) -> contract-valid script.json.

    Post metadata, dialect and (optionally) source_url come from the
    translations file — nothing about a specific video is hardcoded, so a new
    dub project produces correct meta/post. Raises ContractError on any missing
    piece (untranslated scene, absent post block, no source_url)."""
    trans = translations.get("translations")
    if not isinstance(trans, dict):
        raise ContractError(
            f"{TRANSLATIONS}: 'translations' object (id -> Arabic) is required")
    url = (source_url or translations.get("source_url") or "").strip()
    if not url:
        raise ContractError(
            f"dub: source_url is unknown — add a source_url.txt to the project "
            f"or a 'source_url' key to {TRANSLATIONS}")
    post = translations.get("post")
    if not (isinstance(post, dict)
            and isinstance(post.get("title"), str) and post["title"].strip()
            and isinstance(post.get("description"), str)
            and isinstance(post.get("hashtags"), list)):
        raise ContractError(
            f"{TRANSLATIONS}: a 'post' object with non-empty title, "
            f"description and hashtags[] is required (per-project, not hardcoded)")

    seg_list = segs.get("segments")
    if not isinstance(seg_list, list) or not seg_list:
        raise ContractError("dub segments: non-empty 'segments' list required")
    scenes = []
    for s in seg_list:
        ar = trans.get(str(s["id"]))
        if not isinstance(ar, str) or not ar.strip():
            raise ContractError(
                f"{TRANSLATIONS}: no Arabic translation for segment {s['id']}")
        scenes.append({
            "id": s["id"],
            "narration_ar": ar.strip(),
            # placeholders required by validate_script; the dub path never runs
            # the footage stage, so these are inert.
            "keywords": [["dub"]],
            "mood": "calm",
            "target_seconds": round(s["end"] - s["start"], 3),
        })

    story_len = round(segs["story_end"] - segs["story_start"], 3)
    script = {
        "meta": {
            "source_url": url,
            "audience": translations.get("audience", "general Arab"),
            "dialect": translations.get("dialect", "MSA"),
            "target_seconds": story_len,
            "workflow": "dub",
        },
        "hook": scenes[0]["narration_ar"],
        "scenes": scenes,
        "post": {
            "title": post["title"].strip(),
            "description": post["description"].strip(),
            "hashtags": list(post["hashtags"]),
        },
    }
    contract.validate_script(script)
    return script


# ==========================================================================
# Dry-run timing (dub_dryrun) — synthetic per-slot timing, no TTS
# ==========================================================================

def build_dryrun_timing(script: dict, segs: dict) -> dict:
    """Place each scene exactly in its source slot with no word timings
    (captions.py then distributes proportionally). Zero-cost pre-spend check."""
    story_start = float(segs["story_start"])
    total = round(float(segs["story_end"]) - story_start, 3)
    by_id = {s["id"]: s for s in segs["segments"]}
    scenes = []
    for sc in script["scenes"]:
        s = by_id[sc["id"]]
        scenes.append({
            "id": sc["id"],
            "start": round(float(s["start"]) - story_start, 3),
            "end": round(float(s["end"]) - story_start, 3),
            "words": [],
        })
    timing = {"total_seconds": total, "scenes": scenes}
    contract.validate_timing(timing)
    return timing


# ==========================================================================
# Voice placement (dub_voice) — fit each Arabic clip into its scene slot
# ==========================================================================

def place_scenes(raw_durations: list[float], rel_starts: list[float],
                 story_len: float, *, max_speed: float = MAX_SPEED,
                 min_gap: float = MIN_GAP) -> dict:
    """Place each Arabic clip at its source timestamp, fitting into the gap
    before the next scene: natural speed when it fits, gently sped up (atempo,
    capped at max_speed) when it would overrun, pushing later scenes only when
    even the cap is not enough. Returns per-scene {start,end,speed,delay_ms},
    the total timeline length, and the indices that still overran the cap."""
    n = len(raw_durations)
    if len(rel_starts) != n:
        raise ValueError("raw_durations and rel_starts length mismatch")
    placements: list[dict] = []
    overruns: list[int] = []
    prev_end = 0.0
    for i in range(n):
        dur = raw_durations[i]
        start = max(rel_starts[i], prev_end)
        nxt = rel_starts[i + 1] if i < n - 1 else story_len
        available = nxt - start
        speed = 1.0
        if available > min_gap and dur > available:
            speed = min(max_speed, dur / available)
            if dur / speed > available + 1e-3:
                overruns.append(i)
        end = start + dur / speed
        placements.append({
            "start": round(start, 3), "end": round(end, 3),
            "speed": speed, "delay_ms": int(round(start * 1000)),
        })
        prev_end = end
    return {
        "placements": placements,
        "total": round(max(prev_end, story_len), 3),
        "overruns": overruns,
    }


# ==========================================================================
# Render command (dub_render) — source(muted)+voice+captions -> final.mp4
# ==========================================================================

def render_filtergraph(width: int, height: int, fps: int, total: float,
                       band: dict, dub_cfg: dict,
                       has_captions: bool) -> tuple[str, str, dict]:
    """Build the ffmpeg -filter_complex string, video map label, and a report.
    Covers the source's burned-in subtitles with an opaque band and erases its
    watermark (delogo); both tunable via project.yaml dub.*. Pure string
    construction so it is unit-testable without running ffmpeg."""
    filt_extra = ""
    wm = dub_cfg.get("watermark")
    if wm:
        filt_extra += (f",delogo=x={int(wm['x'])}:y={int(wm['y'])}:"
                       f"w={int(wm['w'])}:h={int(wm['h'])}")
    cover_top = int(dub_cfg.get("cover_top", max(0, band["y"] - 12)))
    cover_bottom = int(dub_cfg.get("cover_bottom", height))
    cover_color = str(dub_cfg.get("cover_color", "black"))
    if cover_bottom > cover_top:
        filt_extra += (f",drawbox=x=0:y={cover_top}:w={width}:"
                       f"h={cover_bottom - cover_top}:"
                       f"color={cover_color}@1.0:t=fill")

    base = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1,"
            f"trim=duration={total:.3f},setpts=PTS-STARTPTS{filt_extra},"
            f"format=yuv420p[base]")
    parts = [base]
    if has_captions:
        parts.append(f"[base][2:v]overlay=x=0:y={band['y']}:shortest=0[vout]")
        vlabel = "[vout]"
    else:
        vlabel = "[base]"
    report = {"cover_band": {"top": cover_top, "bottom": cover_bottom,
                             "color": cover_color},
              "watermark_removed": bool(wm)}
    return ";".join(parts), vlabel, report
