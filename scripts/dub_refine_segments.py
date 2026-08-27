"""Dub step 1b: merge whisper fragments into whole sentences.

The raw whisper pass split on a 7s cap, fragmenting some sentences. This
rejoins consecutive fragments until sentence-ending punctuation, trims to the
story window [first_keep .. last_keep] (dropping the channel tagline and the
teaching section), and renumbers. Timing is preserved: merged sentence start =
first fragment start, end = last fragment end.

  .venv\\Scripts\\python.exe scripts\\dub_refine_segments.py romeo-juliet-dub 2 56
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: dub_refine_segments.py <slug> <first_id> <last_id>")
        return 2
    slug, first_id, last_id = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    pdir = ROOT / "projects" / slug
    raw = json.loads((pdir / "dub_segments.json").read_text(encoding="utf-8"))
    kept = [s for s in raw["segments"] if first_id <= s["id"] <= last_id]

    merged: list[dict] = []
    buf: list[dict] = []
    for s in kept:
        buf.append(s)
        if s["en"].rstrip()[-1:] in ".?!":
            merged.append(_join(buf, len(merged) + 1))
            buf = []
    if buf:
        merged.append(_join(buf, len(merged) + 1))

    out = {
        "source": "whisper timing scaffolding (English never enters output)",
        "story_start": merged[0]["start"],
        "story_end": merged[-1]["end"],
        "segments": merged,
    }
    (pdir / "dub_segments.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"merged {len(kept)} fragments -> {len(merged)} sentences")
    print(f"window {out['story_start']:.2f}s -> {out['story_end']:.2f}s")
    return 0


def _join(buf: list[dict], new_id: int) -> dict:
    return {
        "id": new_id,
        "start": buf[0]["start"],
        "end": buf[-1]["end"],
        "en": " ".join(x["en"].strip() for x in buf).strip(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
