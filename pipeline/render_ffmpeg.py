"""Render stage (assembly path A): build final.mp4 with ffmpeg.

Reads script.json (validated), timing.json (the timing truth), clips/,
voiceover.mp3 and captions/manifest.json; writes final.mp4 and
render_report.json.

Design notes:
- timing.json durations rule the cut; script target_seconds is never used.
- A missing scene clip never fails the render: a neutral placeholder is
  substituted and recorded as a gap in render_report.json so the review
  gate surfaces it.
- Captions are pre-shaped RGBA PNGs (pipeline/captions.py owns Arabic
  shaping — CLAUDE.md rule 3; libass is never used). Here they become one
  transparent video track: a concat-demuxer list of PNGs with per-frame
  durations (gaps filled with a fully transparent PNG so the track runs
  continuously from 0 to total duration, last entry repeated per the
  concat-demuxer convention), encoded to captions.mov with -c:v png and
  overlaid in a single pass.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from pipeline import contract
from pipeline.contract import ContractError, Project, ffmpeg_path
from pipeline.errors import StageError

STAGE = "render"

# Cross-stage file names come from contract.py (the single source of truth).
RENDER_REPORT = contract.RENDER_REPORT
CAPTIONS_DIR = contract.CAPTIONS_DIR
CAPTIONS_MANIFEST = contract.CAPTIONS_MANIFEST

# Stage-private scratch artifacts (never read by another stage).
WORK_DIR = "render_work"
CAPTIONS_MOV = "captions.mov"
CAPTION_LIST = "captions_concat.txt"
GAP_PNG = "_gap.png"
ICONS_DIR = contract.ROOT / "assets" / "icons"  # pop-in emphasis icon PNGs

PLACEHOLDER_COLOR = "0x202030"
MUSIC_EXTS = {".mp3", ".m4a", ".wav"}
_EPS = 1e-3


def run(project: Project, cfg: dict, env: dict, *, force: bool = False) -> None:
    final_path = project.path(contract.FINAL)
    report_path = project.path(RENDER_REPORT)
    if final_path.exists() and report_path.exists() and not force:
        return

    width = int(_need(cfg.get("video"), "width", "video"))
    height = int(_need(cfg.get("video"), "height", "video"))
    fps = _need(cfg.get("video"), "fps", "video")
    acfg = cfg.get("audio")
    if not isinstance(acfg, dict):
        raise ContractError("config: 'audio' section is required for render")

    script = project.script()  # validate the spine; timing.json drives the cut
    icon_by_id = {int(s["id"]): s["icon"]
                  for s in script["scenes"] if s.get("icon")}
    timing = project.timing()
    total = float(timing["total_seconds"])
    scenes = sorted(timing["scenes"], key=lambda s: float(s["start"]))

    # Pop-in emphasis icons: (png, appear_time, end_time) per scene that sets an
    # `icon`; the icon fades in ~30% into the scene and holds to the scene end.
    icon_specs: list[tuple[Path, float, float]] = []
    for s in scenes:
        name = icon_by_id.get(int(s["id"]))
        if not name:
            continue
        png = ICONS_DIR / f"{name}.png"
        if not png.exists():
            continue
        st, en = float(s["start"]), float(s["end"])
        icon_specs.append((png, st + min(0.6, 0.30 * (en - st)), en))

    voice_path = project.path(contract.VOICEOVER)
    if not voice_path.exists():
        raise ContractError(
            f"{contract.VOICEOVER} missing — run the voice stage first"
        )

    entries, band = _load_manifest(project, height, cfg)

    work = project.path(WORK_DIR)
    work.mkdir(exist_ok=True)

    report: dict[str, Any] = {"scenes": [], "gaps": [], "commands": []}

    # The voiceover and the caption track live on the ABSOLUTE [0, total]
    # timeline, so the video track must tile it exactly: scene k's visuals
    # run from its own start (first scene: from 0, absorbing leading
    # silence) to the next scene's start (last scene: to total). Bare
    # per-scene durations would silently desync everything as soon as
    # timing.json has gaps — which align.py's fallback legitimately writes.
    fps_f = float(fps)
    frame_counts = _cut_frame_counts(scenes, total, fps_f)

    scene_rows: list[tuple[float, Path | None]] = []
    for s, n_frames in zip(scenes, frame_counts):
        # Half a frame below the cut keeps trim from emitting an extra
        # frame at an exact boundary; each segment is exactly n_frames long.
        dur = (n_frames - 0.5) / fps_f
        clip = project.clip_for_scene(int(s["id"]))
        if clip is None:
            report["gaps"].append(int(s["id"]))
        report["scenes"].append({
            "id": int(s["id"]),
            "start": float(s["start"]),
            "end": float(s["end"]),
            "duration": round(n_frames / fps_f, 3),
            "clip": clip.relative_to(project.dir).as_posix() if clip else None,
            "placeholder": clip is None,
        })
        scene_rows.append((dur, clip))

    captions_mov = _build_caption_track(entries, band, total, work,
                                        report, project)

    music = _pick_music(cfg)
    report["music"] = music.as_posix() if music else None

    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-nostats", "-nostdin"]
    for dur, clip in scene_rows:
        if clip is not None:
            cmd += ["-i", str(clip)]
        else:
            cmd += ["-f", "lavfi", "-i",
                    f"color=c={PLACEHOLDER_COLOR}:s={width}x{height}"
                    f":r={fps}:d={dur:.3f}"]
    n = len(scene_rows)
    next_idx = n
    cap_idx = None
    if captions_mov is not None:
        cap_idx = next_idx
        next_idx += 1
        cmd += ["-i", str(captions_mov)]
    icon_idx: list[int] = []
    for png, _appear, _end in icon_specs:
        icon_idx.append(next_idx)
        next_idx += 1
        # Bound the looped still to the timeline (finite + light): an unbounded
        # `-loop 1` image input makes ffmpeg churn and the encode never ends.
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{total:.3f}",
                "-i", str(png)]
    voice_idx = next_idx
    next_idx += 1
    cmd += ["-i", str(voice_path)]
    music_idx = None
    if music is not None:
        music_idx = next_idx
        cmd += ["-i", str(music)]

    parts = [
        _scene_filter(i, dur, width, height, fps, placeholder=clip is None)
        for i, (dur, clip) in enumerate(scene_rows)
    ]
    parts.append("".join(f"[v{i}]" for i in range(n))
                 + f"concat=n={n}:v=1:a=0[vcat]")
    if cap_idx is not None:
        parts.append(
            f"[vcat][{cap_idx}:v]overlay=x=0:y={band['y']}:shortest=1[vout]"
        )
        vlabel = "[vout]"
    else:
        vlabel = "[vcat]"

    # Pop-in emphasis icons: each fades in at its scene's beat, held to the
    # scene end, in the upper area (clear of the lower caption band).
    if icon_specs:
        iw = round(width * 0.15)
        ix = round(width * 0.58)
        iy = round(height * 0.10)
        cur = vlabel
        for k, (_png, appear, end) in enumerate(icon_specs):
            parts.append(
                f"[{icon_idx[k]}:v]scale={iw}:-1,fps={fps},format=rgba,"
                f"fade=t=in:st={appear:.3f}:d=0.30:alpha=1[ic{k}]"
            )
            parts.append(
                f"{cur}[ic{k}]overlay=x={ix}:y={iy}:"
                f"enable='between(t,{appear:.3f},{end:.3f})'[vic{k}]"
            )
            cur = f"[vic{k}]"
        vlabel = cur

    # Gentle fade from/to black on the whole picture: a fade-in on the open and a
    # fade-out that matches the music's outro so the ending doesn't hard-cut
    # against a fading track (research: a hard visual cut reads as unfinished).
    vlabel = _apply_video_fades(parts, vlabel, total, cfg, acfg)

    parts.append(_audio_filter(voice_idx, music_idx, total, acfg))

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", vlabel, "-map", "[aout]",
        "-c:v", "libx264", "-crf", "19", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        str(final_path),
    ]
    _exec(cmd, report, project)

    report["output"] = _probe(final_path, report, project)
    project.write_json(RENDER_REPORT, report)


def _cut_frame_counts(scenes: list[dict], total: float, fps: float) -> list[int]:
    """Frame count per scene segment on the absolute timeline.

    Scene k's segment runs from its own start (first scene: from 0) to the
    next scene's start (last scene: to total_seconds), so the concatenated
    video tiles [0, total] exactly like the voiceover/caption tracks even
    when timing.json has leading silence, inter-scene gaps or small
    overlaps (align.py's whisper fallback produces all three). Cut points
    are quantized to the frame grid CUMULATIVELY so per-scene rounding can
    never accumulate into A/V drift, and every scene emits at least one
    frame (a zero-frame segment would break the concat filter).
    """
    cuts = [0.0] + [float(s["start"]) for s in scenes[1:]] + [float(total)]
    frames = [round(t * fps) for t in cuts]
    for k in range(1, len(frames)):
        frames[k] = max(frames[k], frames[k - 1] + 1)
    return [frames[k + 1] - frames[k] for k in range(len(scenes))]


# --------------------------------------------------------------------------
# Captions track
# --------------------------------------------------------------------------

def _load_manifest(
    project: Project, video_h: int, cfg: dict
) -> tuple[list[tuple[Path, float, float]], dict[str, int]]:
    """Parse captions/manifest.json -> (sorted entries, band geometry).

    Accepts either a bare entry list or {"band": {...}, "entries": [...]}
    (band keys may also sit at the top level). Entries: png/start/end.
    Also accepts the exact shape pipeline/captions.py writes:
    {"width": W, "band_height": H, "y": Y, "frames": [...]}.
    """
    cap_dir = project.dir / CAPTIONS_DIR
    mpath = cap_dir / CAPTIONS_MANIFEST
    if not mpath.exists():
        raise ContractError(
            f"{CAPTIONS_DIR}/{CAPTIONS_MANIFEST} missing — "
            f"run the captions stage first"
        )
    with open(mpath, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ContractError(
                f"{CAPTIONS_DIR}/{CAPTIONS_MANIFEST} is not valid JSON: {exc}"
            ) from exc

    band_raw: dict[str, Any] = {}
    if isinstance(data, list):
        raw_entries = data
    elif isinstance(data, dict):
        raw_entries = data.get("entries")
        if raw_entries is None:
            raw_entries = data.get("frames")  # captions.py writes "frames"
        if not isinstance(raw_entries, list):
            raise ContractError(
                f"{CAPTIONS_MANIFEST}: 'entries' or 'frames' list is required")
        if isinstance(data.get("band"), dict):
            band_raw = data["band"]
        else:
            band_raw = {k: data[k] for k in ("width", "height", "y")
                        if k in data}
            if "height" not in band_raw and isinstance(
                    data.get("band_height"), (int, float)):
                band_raw["height"] = data["band_height"]
    else:
        raise ContractError(f"{CAPTIONS_MANIFEST} must be a list or object")

    entries: list[tuple[Path, float, float]] = []
    for i, e in enumerate(raw_entries):
        where = f"{CAPTIONS_MANIFEST} entries[{i}]"
        if not (isinstance(e, dict) and isinstance(e.get("png"), str)
                and isinstance(e.get("start"), (int, float))
                and isinstance(e.get("end"), (int, float))):
            raise ContractError(f"{where}: needs png/start/end")
        if float(e["end"]) <= float(e["start"]):
            raise ContractError(f"{where}: end must be > start")
        png = Path(e["png"])
        if not png.is_absolute():
            candidate = cap_dir / png
            png = candidate if candidate.exists() else project.dir / png
        if not png.exists():
            raise ContractError(f"{where}: caption frame not found: {e['png']}")
        entries.append((png, float(e["start"]), float(e["end"])))
    entries.sort(key=lambda t: t[1])

    if not entries:
        return [], {"width": 0, "height": 0, "y": 0}

    bw = int(band_raw.get("width") or 0)
    bh = int(band_raw.get("height") or 0)
    if not bw or not bh:
        with Image.open(entries[0][0]) as im:
            bw, bh = im.size
    y = band_raw.get("y")
    if y is None:
        # fall back to the caption style margin: band sits above margin_v
        margin = (cfg.get("captions") or {}).get("margin_v")
        if margin is None:
            raise ContractError(
                f"{CAPTIONS_MANIFEST}: band 'y' missing and no "
                f"captions.margin_v in config to derive it"
            )
        y = video_h - bh - int(margin)
    return entries, {"width": bw, "height": bh, "y": int(y)}


def _caption_segments(
    entries: list[tuple[Path, float, float]], total: float
) -> list[tuple[Path | None, float]]:
    """Continuous (png|None, duration) segments covering [0, total].

    None marks a gap to be filled with the transparent PNG.
    """
    segs: list[tuple[Path | None, float]] = []
    t = 0.0
    for png, start, end in entries:
        start = max(start, t)
        end = min(end, total)
        if end - start <= _EPS:
            continue
        if start - t > _EPS:
            segs.append((None, start - t))
        segs.append((png, end - start))
        t = end
    if total - t > _EPS:
        segs.append((None, total - t))
    return segs


def _quote_concat(path: Path) -> str:
    return path.as_posix().replace("'", r"'\''")


def _write_caption_list(segments: list[tuple[Path | None, float]],
                        gap_png: Path, list_path: Path) -> None:
    lines = ["ffconcat version 1.0"]
    last: Path | None = None
    for png, dur in segments:
        p = gap_png if png is None else png
        # Absolute: ffconcat resolves relative `file` entries against the list
        # file's own directory, doubling a project-relative path (render_work/
        # projects/.../render_work/_gap.png) when the project dir is relative.
        lines.append(f"file '{_quote_concat(p.resolve())}'")
        lines.append(f"duration {dur:.6f}")
        last = p
    # repeat the last file so its duration is honoured (concat demuxer
    # convention) and the track EOFs at total duration, not earlier —
    # the overlay runs with shortest=1.
    if last is not None:
        lines.append(f"file '{_quote_concat(last.resolve())}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_caption_track(entries: list[tuple[Path, float, float]],
                         band: dict[str, int], total: float, work: Path,
                         report: dict, project: Project) -> Path | None:
    segments = _caption_segments(entries, total)
    n_gaps = sum(1 for png, _ in segments if png is None)
    report["captions"] = {
        "pages": len(entries),
        "gap_entries": n_gaps,
        "band": band if entries else None,
    }
    if not entries:
        return None
    gap_png = work / GAP_PNG
    Image.new("RGBA", (band["width"], band["height"]), (0, 0, 0, 0)).save(
        gap_png)
    list_path = work / CAPTION_LIST
    _write_caption_list(segments, gap_png, list_path)
    captions_mov = work / CAPTIONS_MOV
    cmd = [
        ffmpeg_path(), "-y", "-hide_banner", "-nostats", "-nostdin",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        # normalize every page to the band geometry and force RGBA so the
        # stream never changes format mid-track
        "-vf", f"scale={band['width']}:{band['height']},format=rgba",
        "-c:v", "png", "-fps_mode", "vfr",
        str(captions_mov),
    ]
    _exec(cmd, report, project)
    return captions_mov


# --------------------------------------------------------------------------
# Filtergraph pieces
# --------------------------------------------------------------------------

def _scene_filter(idx: int, dur: float, w: int, h: int, fps: Any,
                  *, placeholder: bool) -> str:
    d = f"{dur:.3f}"
    if placeholder:
        # lavfi color source already has the right size/rate/duration
        return f"[{idx}:v]fps={fps},setsar=1,format=yuv420p[v{idx}]"
    return (
        f"[{idx}:v]trim=duration={d},setpts=PTS-STARTPTS,"
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"fps={fps},setsar=1,format=yuv420p,"
        # clip shorter than the scene -> freeze last frame; timing.json wins
        f"tpad=stop_mode=clone:stop_duration={d},"
        f"trim=duration={d},setpts=PTS-STARTPTS[v{idx}]"
    )


def _audio_filter(voice_idx: int, music_idx: int | None, total: float,
                  acfg: dict) -> str:
    lufs = _need(acfg, "loudness_lufs", "audio")
    master = f"loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000[aout]"
    if music_idx is None:
        return f"[{voice_idx}:a]{master}"
    gain = _need(acfg, "music_gain_db", "audio")
    thr = _need(acfg, "duck_threshold", "audio")
    ratio = _need(acfg, "duck_ratio", "audio")
    # Gentle sidechain (research 2026): attack catches word onsets, a slow release
    # recovers like breathing (no pumping), soft knee smooths it. A hard ratio +
    # low threshold behaves as a noise gate and makes the bed vanish.
    attack = acfg.get("duck_attack", 15)
    release = acfg.get("duck_release", 400)
    knee = acfg.get("duck_knee", 6)
    duck = (f"sidechaincompress=threshold={thr}:ratio={ratio}"
            f":attack={attack}:release={release}:makeup=1:knee={knee}")
    # Graceful music fade-out at the end — applied to the BED only, so the final
    # narration is untouched (a hard cut read as "sound stops like bad editing").
    outro = float(acfg.get("outro_fade", 2.0))
    fstart = max(0.0, total - outro)
    bed_outro = f",afade=t=out:st={fstart:.3f}:d={outro:.3f}" if outro > 0 else ""
    return (
        f"[{voice_idx}:a]asplit=2[vo_mix][vo_sc];"
        f"[{music_idx}:a]aloop=loop=-1:size=2147483647,"
        f"atrim=duration={total:.3f},volume={gain}dB[bed];"
        f"[bed][vo_sc]{duck}[duck];"
        f"[duck]{_entrance_chain(acfg)}{bed_outro}[bedf];"
        f"[vo_mix][bedf]amix=inputs=2:duration=first,{master}"
    )


def _entrance_chain(acfg: dict) -> str:
    """Filters applied to the ducked bed so the music *enters* under the opening
    hook and then settles to its normal (ducked) level — the 'entrance music'
    the reference channel has. A fade from silence, then a time-varying gain that
    holds high for `entrance_seconds` and ramps back to unity. All keys optional;
    set entrance_seconds: 0 to disable and get the plain ducked bed."""
    es = float(acfg.get("entrance_seconds", 2.0))
    fade = float(acfg.get("intro_fade", 0.8))
    if es <= 0:
        return "anull"
    g = 10 ** (float(acfg.get("entrance_gain_db", 8.0)) / 20.0)  # dB -> linear
    ramp = float(acfg.get("entrance_ramp", 1.2))
    # eval=frame so the gain follows t; commas are protected by the single quotes.
    env = (
        f"volume=volume='if(lt(t,{es:.3f}),{g:.4f},"
        f"if(lt(t,{es + ramp:.3f}),{g:.4f}-({g:.4f}-1)*(t-{es:.3f})/{ramp:.3f},1))'"
        f":eval=frame"
    )
    return f"afade=t=in:st=0:d={fade:.3f},{env}"


def _apply_video_fades(parts: list, vlabel: str, total: float, cfg: dict,
                       acfg: dict) -> str:
    """Append a fade-in/out on the final picture and return the new video label.
    The fade-out length defaults to the music outro so audio + picture resolve
    together. Config: video.fade_in / video.fade_out (0 disables either)."""
    vcfg = cfg.get("video") or {}
    fin = float(vcfg.get("fade_in", 0.5))
    fout = float(vcfg.get("fade_out", acfg.get("outro_fade", 2.0)))
    steps = []
    if fin > 0:
        steps.append(f"fade=t=in:st=0:d={fin:.3f}")
    if fout > 0:
        steps.append(f"fade=t=out:st={max(0.0, total - fout):.3f}:d={fout:.3f}")
    if not steps:
        return vlabel
    parts.append(f"{vlabel}{','.join(steps)}[vfinal]")
    return "[vfinal]"


def _pick_music(cfg: dict) -> Path | None:
    """First *.mp3/*.m4a/*.wav alphabetically in audio.music_dir, or None."""
    music_dir = (cfg.get("audio") or {}).get("music_dir")
    if not music_dir:
        return None
    d = Path(music_dir)
    if not d.is_absolute():
        d = contract.ROOT / d
    if not d.is_dir():
        return None
    files = sorted(
        (p for p in d.iterdir()
         if p.is_file() and p.suffix.lower() in MUSIC_EXTS),
        key=lambda p: p.name.lower(),
    )
    return files[0] if files else None


# --------------------------------------------------------------------------
# Process plumbing
# --------------------------------------------------------------------------

def _need(section: Any, key: str, name: str) -> Any:
    if not isinstance(section, dict) or key not in section:
        raise ContractError(f"config: {name}.{key} is required for render")
    return section[key]


def _exec(cmd: list[str], report: dict,
          project: Project) -> subprocess.CompletedProcess:
    report["commands"].append(list(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-30:])
        report["error"] = {
            "command": list(cmd),
            "returncode": proc.returncode,
            "stderr_tail": tail,
        }
        project.write_json(RENDER_REPORT, report)
        raise StageError(
            STAGE,
            f"{Path(cmd[0]).name} failed (exit {proc.returncode}):\n{tail}",
        )
    return proc


def _probe(path: Path, report: dict, project: Project) -> dict[str, Any]:
    cmd = [
        ffmpeg_path("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = _exec(cmd, report, project)
    data = json.loads(proc.stdout or "{}")
    out: dict[str, Any] = {"duration": None, "width": None, "height": None}
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        out["duration"] = float(fmt["duration"])
    for st in data.get("streams") or []:
        if st.get("codec_type") == "video":
            out["width"] = st.get("width")
            out["height"] = st.get("height")
            break
    return out


# --------------------------------------------------------------------------
# Public, stable aliases for reuse by the dub workflow (pipeline/dub.py) and
# tests. The underscore versions remain the implementation; import these so
# the dub path never reaches into private render internals.
# --------------------------------------------------------------------------
load_manifest = _load_manifest
build_caption_track = _build_caption_track
probe = _probe
