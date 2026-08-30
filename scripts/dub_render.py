"""Dub step 5: source.mp4 + voiceover.mp3 + captions -> final.mp4.

The video is the ORIGINAL footage (muted), scaled/padded to the canvas, with
the source's burned-in subtitles covered by an opaque band and its watermark
erased (delogo) — both tunable via project.yaml dub.* (pipeline.dub builds the
filtergraph). The Arabic voiceover goes on top and the pre-shaped caption PNGs
are burned in via render_ffmpeg's caption-track builder (Arabic stays on the
Pillow+raqm path — Hard Rule 3; libass is never used).

Timeline: voiceover.mp3 and captions.mov are absolute [0, total]; the source is
seeked to the story start and trimmed to `total` so all three align.

  .venv\\Scripts\\python.exe scripts\\dub_render.py <slug> [--force]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract, dub  # noqa: E402
from pipeline.contract import ffmpeg_path  # noqa: E402

CAPTIONS_MANIFEST_REL = f"{contract.CAPTIONS_DIR}/{contract.CAPTIONS_MANIFEST}"


def main() -> int:
    ap = argparse.ArgumentParser(description="dub step 5: final render")
    ap.add_argument("slug")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    pdir = ROOT / "projects" / args.slug
    project = contract.Project(pdir)
    cfg = contract.load_config(pdir)

    final_path = project.path(contract.FINAL)
    if final_path.exists() and not args.force:
        print("final.mp4 already present (use --force)")
        return 0

    for need, hint in ((contract.VOICEOVER, "run dub_voice.py first"),
                       (contract.TIMING, "run dub_voice.py first"),
                       (CAPTIONS_MANIFEST_REL, "run the captions stage first")):
        if not project.has(need):
            print(f"ERROR: {need} missing — {hint}")
            return 1
    src = pdir / contract.SOURCE_VIDEO
    if not src.exists():
        print(f"ERROR: {contract.SOURCE_VIDEO} missing")
        return 1

    try:
        segs = dub.load_segments(project)
        timing = project.timing()
    except contract.ContractError as exc:
        print(f"ERROR: {exc}")
        return 1

    vcfg = cfg["video"]
    W, H, FPS = int(vcfg["width"]), int(vcfg["height"]), int(vcfg["fps"])
    lufs = cfg["audio"]["loudness_lufs"]
    total = float(timing["total_seconds"])
    story_start = float(segs["story_start"])
    dcfg = cfg.get("dub") or {}

    work = pdir / "render_work"; work.mkdir(exist_ok=True)
    report: dict = {"workflow": "dub", "commands": []}
    entries, band = dub.load_manifest(project, H, cfg)
    captions_mov = dub.build_caption_track(entries, band, total, work, report,
                                           project)

    graph, vlabel, cover_report = dub.render_filtergraph(
        W, H, FPS, total, band, dcfg, has_captions=captions_mov is not None)
    report.update(cover_report)

    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-nostats", "-nostdin",
           "-ss", f"{story_start:.3f}", "-i", str(src),
           "-i", str(project.path(contract.VOICEOVER))]
    if captions_mov is not None:
        cmd += ["-i", str(captions_mov)]
    audio = (f"[1:a]loudnorm=I={lufs}:TP=-1.5:LRA=11,"
             f"apad,atrim=0:{total:.3f},aresample=48000[aout]")
    cmd += ["-filter_complex", f"{graph};{audio}",
            "-map", vlabel, "-map", "[aout]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-crf", "19", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k", str(final_path)]
    report["commands"].append(list(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-25:])
        report["error"] = tail
        project.write_json("dub_render_report.json", report)
        print(f"ERROR: render failed:\n{tail}")
        return 1

    report["output"] = dub.probe(final_path, report, project)
    report["duration"] = total
    report["canvas"] = f"{W}x{H}"
    project.write_json("dub_render_report.json", report)
    out = report["output"]
    print(f"wrote final.mp4 : {out.get('width')}x{out.get('height')} "
          f"{out.get('duration')}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
