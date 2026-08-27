"""Dub dry-run: exercise captions + render with NO TTS (no API cost).

Builds a synthetic timing.json placing each scene exactly in its source-video
slot (words omitted -> captions.py distributes them proportionally) and a
silent voiceover.mp3 of the story length. Lets us verify Arabic caption
shaping/placement on real rendered frames and the whole assembly path before
spending any ElevenLabs characters. The real dub_voice.py overwrites both
files with billed audio + exact word timings.

  .venv\\Scripts\\python.exe scripts\\dub_dryrun.py romeo-juliet-dub
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract  # noqa: E402
from pipeline.contract import ffmpeg_path  # noqa: E402


def main() -> int:
    slug = sys.argv[1] if len(sys.argv) > 1 else "romeo-juliet-dub"
    pdir = ROOT / "projects" / slug
    project = contract.Project(pdir)
    script = project.script()
    segs = json.loads((pdir / "dub_segments.json").read_text(encoding="utf-8"))
    story_start = float(segs["story_start"])
    story_len = round(float(segs["story_end"]) - story_start, 3)
    seg_by_id = {s["id"]: s for s in segs["segments"]}

    scenes = []
    for sc in script["scenes"]:
        s = seg_by_id[sc["id"]]
        scenes.append({
            "id": sc["id"],
            "start": round(float(s["start"]) - story_start, 3),
            "end": round(float(s["end"]) - story_start, 3),
            "words": [],   # captions.py falls back to proportional timing
        })
    timing = {"total_seconds": story_len, "scenes": scenes}
    contract.validate_timing(timing)
    project.write_json(contract.TIMING, timing)

    # Silent voiceover of the story length so render has an audio input.
    voice_path = project.path(contract.VOICEOVER)
    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i",
           f"anullsrc=channel_layout=stereo:sample_rate=48000",
           "-t", f"{story_len:.3f}", "-c:a", "libmp3lame", "-b:a", "128k",
           str(voice_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print("ERROR: silence gen failed:", proc.stderr[-300:])
        return 1
    print(f"dry-run timing.json ({len(scenes)} scenes, {story_len:.1f}s) "
          f"+ silent voiceover.mp3 written")
    print("next: run captions stage, then scripts/dub_render.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
