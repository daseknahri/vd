"""Dub step 5: source.mp4 + voiceover.mp3 + captions -> final.mp4.

The video is the ORIGINAL footage (muted), scaled/padded to the 16:9 canvas,
with the Arabic voiceover on top and the pre-shaped caption PNGs burned in.
Reuses render_ffmpeg's caption-track builder (concat of RGBA PNGs -> captions.mov)
and its manifest loader, so Arabic shaping still goes only through the
Pillow+raqm frames (CLAUDE.md rule 3 — libass is never used).

Timeline: voiceover.mp3 and captions.mov are absolute [0, total]; the source
is seeked to the story start and trimmed to `total` so all three align.

  .venv\\Scripts\\python.exe scripts\\dub_render.py romeo-juliet-dub
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract  # noqa: E402
from pipeline import render_ffmpeg as rf  # noqa: E402
from pipeline.contract import ffmpeg_path  # noqa: E402


def main() -> int:
    slug = sys.argv[1] if len(sys.argv) > 1 else "romeo-juliet-dub"
    force = "--force" in sys.argv[2:]
    pdir = ROOT / "projects" / slug
    project = contract.Project(pdir)
    cfg = contract.load_config(pdir)

    final_path = project.path(contract.FINAL)
    if final_path.exists() and not force:
        print("final.mp4 already present (use --force)")
        return 0

    for need in (contract.VOICEOVER, contract.TIMING):
        if not project.has(need):
            print(f"ERROR: {need} missing — run dub_voice.py first")
            return 1
    src = pdir / "source.mp4"
    if not src.exists():
        print("ERROR: source.mp4 missing")
        return 1

    vcfg = cfg["video"]
    W, H, FPS = int(vcfg["width"]), int(vcfg["height"]), int(vcfg["fps"])
    lufs = cfg["audio"]["loudness_lufs"]

    timing = project.timing()
    total = float(timing["total_seconds"])
    segs = json.loads((pdir / "dub_segments.json").read_text(encoding="utf-8"))
    story_start = float(segs["story_start"])

    work = pdir / "render_work"; work.mkdir(exist_ok=True)
    report: dict = {"workflow": "dub", "commands": []}

    entries, band = rf._load_manifest(project, H, cfg)
    captions_mov = rf._build_caption_track(entries, band, total, work,
                                           report, project)

    # The source is a "listening practice" video with its OWN English
    # subtitles burned into the lower third. Cover that band with an opaque
    # bar so only the Arabic captions show. Tunable via project.yaml
    # dub.cover_top / dub.cover_color; default hides from just above the
    # Arabic band down to the frame bottom.
    dcfg = cfg.get("dub") or {}
    filt_extra = ""
    # 1. Erase the source's static channel watermark (top-right) with delogo,
    #    which interpolates the surrounding pixels instead of leaving a box.
    wm = dcfg.get("watermark")
    if wm:
        filt_extra += (f",delogo=x={int(wm['x'])}:y={int(wm['y'])}:"
                       f"w={int(wm['w'])}:h={int(wm['h'])}")
    # 2. Cover the source's burned-in English subtitles with an opaque band.
    #    cover_bottom defaults to the frame bottom; set it above H for a
    #    floating subtitle band that shows the scene below it.
    cover_top = int(dcfg.get("cover_top", max(0, band["y"] - 12)))
    cover_bottom = int(dcfg.get("cover_bottom", H))
    cover_color = str(dcfg.get("cover_color", "black"))
    if cover_bottom > cover_top:
        filt_extra += (f",drawbox=x=0:y={cover_top}:w={W}:"
                       f"h={cover_bottom - cover_top}:"
                       f"color={cover_color}@1.0:t=fill")
    report["cover_band"] = {"top": cover_top, "bottom": cover_bottom,
                            "color": cover_color}
    report["watermark_removed"] = bool(wm)

    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-nostats", "-nostdin",
           "-ss", f"{story_start:.3f}", "-i", str(src),
           "-i", str(project.path(contract.VOICEOVER))]
    if captions_mov is not None:
        cmd += ["-i", str(captions_mov)]

    base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},setsar=1,"
            f"trim=duration={total:.3f},setpts=PTS-STARTPTS{filt_extra},"
            f"format=yuv420p[base]")
    parts = [base]
    if captions_mov is not None:
        parts.append(f"[base][2:v]overlay=x=0:y={band['y']}:shortest=0[vout]")
        vlabel = "[vout]"
    else:
        vlabel = "[base]"
    parts.append(
        f"[1:a]loudnorm=I={lufs}:TP=-1.5:LRA=11,"
        f"apad,atrim=0:{total:.3f},aresample=48000[aout]"
    )

    cmd += ["-filter_complex", ";".join(parts),
            "-map", vlabel, "-map", "[aout]",
            "-t", f"{total:.3f}",
            "-c:v", "libx264", "-crf", "19", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            str(final_path)]

    report["commands"].append(list(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-25:])
        report["error"] = tail
        project.write_json("dub_render_report.json", report)
        print(f"ERROR: render failed:\n{tail}")
        return 1

    report["output"] = rf._probe(final_path, report, project)
    report["duration"] = total
    report["canvas"] = f"{W}x{H}"
    project.write_json("dub_render_report.json", report)
    out = report["output"]
    print(f"wrote final.mp4 : {out.get('width')}x{out.get('height')} "
          f"{out.get('duration')}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
