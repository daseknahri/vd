"""Dub step 1b: merge whisper fragments into whole sentences.

The raw whisper pass (dub_segments.json) may split a sentence across fragments.
This rejoins consecutive fragments in id-range [first..last] into whole
sentences and writes dub_segments.refined.json — leaving the raw file intact
(so this is re-runnable and the raw whisper output is never destroyed).
Downstream steps prefer the refined file when present (pipeline.dub.load_segments).

  .venv\\Scripts\\python.exe scripts\\dub_refine_segments.py <slug> <first_id> <last_id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract, dub  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="dub step 1b: merge fragments")
    ap.add_argument("slug")
    ap.add_argument("first_id", type=int)
    ap.add_argument("last_id", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    pdir = ROOT / "projects" / args.slug
    project = contract.Project(pdir)
    if project.has(dub.SEGMENTS_REFINED) and not args.force:
        print(f"{dub.SEGMENTS_REFINED} already present (use --force)")
        return 0
    if not project.has(dub.SEGMENTS):
        print(f"ERROR: {dub.SEGMENTS} not found — run dub_segment.py first")
        return 1

    try:
        raw = project.read_json(dub.SEGMENTS)
        out = dub.refine_segments(raw, args.first_id, args.last_id)
    except contract.ContractError as exc:
        print(f"ERROR: {exc}")
        return 1

    project.write_json(dub.SEGMENTS_REFINED, out)
    n_kept = sum(1 for s in raw["segments"]
                 if args.first_id <= s["id"] <= args.last_id)
    print(f"merged {n_kept} fragments -> {len(out['segments'])} sentences "
          f"({out['story_start']:.2f}s -> {out['story_end']:.2f}s)")
    print(f"wrote {pdir / dub.SEGMENTS_REFINED} (raw {dub.SEGMENTS} kept)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
