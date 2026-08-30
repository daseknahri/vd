"""Dub dry-run: exercise captions + render with NO TTS (no API cost).

Builds a synthetic timing.json (each scene in its source slot; captions.py then
distributes words proportionally) and a silent voiceover.mp3 of the story
length, so Arabic caption shaping/placement and the whole assembly path can be
verified before spending any ElevenLabs characters.

SAFETY: refuses to overwrite a REAL voiceover.mp3/timing.json unless --force,
so a dry-run can never silently destroy billed audio.

  .venv\\Scripts\\python.exe scripts\\dub_dryrun.py <slug> [--force]
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


def main() -> int:
    ap = argparse.ArgumentParser(description="dub dry-run (no TTS)")
    ap.add_argument("slug")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing voiceover/timing with the dry-run")
    args = ap.parse_args()

    pdir = ROOT / "projects" / args.slug
    project = contract.Project(pdir)
    if (project.has(contract.VOICEOVER) or project.has(contract.TIMING)) \
            and not args.force:
        print("refusing to overwrite existing voiceover.mp3/timing.json with a "
              "silent dry-run — pass --force if that is intended "
              "(a real billed voiceover may be present).")
        return 1

    try:
        script = project.script()
        segs = dub.load_segments(project)
        timing = dub.build_dryrun_timing(script, segs)
    except contract.ContractError as exc:
        print(f"ERROR: {exc}")
        return 1
    project.write_json(contract.TIMING, timing)

    story_len = timing["total_seconds"]
    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
           "-t", f"{story_len:.3f}", "-c:a", "libmp3lame", "-b:a", "128k",
           str(project.path(contract.VOICEOVER))]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print("ERROR: silence gen failed:", (proc.stderr or "")[-300:])
        return 1
    print(f"dry-run timing.json ({len(timing['scenes'])} scenes, {story_len:.1f}s) "
          f"+ silent voiceover.mp3 written")
    print("next: run the captions stage, then scripts/dub_render.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
