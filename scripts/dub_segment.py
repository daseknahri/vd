"""Dub step 1: source video -> timed English sentences (research/timing only).

Runs faster-whisper on the source audio with word timestamps, isolates the
story window (up to a configurable end marker), and groups words into
caption-sized sentences with precise (start, end) times. Output feeds the
translation step; NOTHING here is copied into the final video's audio or text
— the English is timing scaffolding only.

The story-end marker defaults to pipeline.dub.DEFAULT_STORY_END_MARKER; override
per project via project.yaml `dub.story_end_marker`, or on the CLI with
`--marker "phrase"`. When no marker matches, the WHOLE transcript is used and a
loud warning is printed (a different source video needs its own marker).

Console output stays ASCII (CLAUDE.md rule 4). Run from repo root:
  .venv\\Scripts\\python.exe scripts\\dub_segment.py <slug> [--marker "phrase"]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract, dub  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="dub step 1: whisper segmentation")
    ap.add_argument("slug", help="project folder under projects/")
    ap.add_argument("--marker", default=None,
                    help="story-end phrase (overrides project.yaml dub.story_end_marker)")
    ap.add_argument("--force", action="store_true",
                    help="re-run even if dub_segments.json exists")
    args = ap.parse_args()

    pdir = ROOT / "projects" / args.slug
    project = contract.Project(pdir)
    if project.has(dub.SEGMENTS) and not args.force:
        print(f"{dub.SEGMENTS} already present (use --force to re-run)")
        return 0
    src = pdir / contract.SOURCE_VIDEO
    if not src.exists():
        print(f"ERROR: {src} not found. Download the source first, e.g.:\n"
              f"  .venv\\Scripts\\python.exe -m yt_dlp "
              f'--extractor-args "youtube:player_client=android" -f 18 '
              f'-o "{src}" <URL>\n'
              f"  (see DUB.md 'Downloading the source' for HD options)")
        return 1

    cfg = contract.load_config(pdir)
    marker = (args.marker
              or (cfg.get("dub") or {}).get("story_end_marker")
              or dub.DEFAULT_STORY_END_MARKER)

    from faster_whisper import WhisperModel
    print("loading whisper (small, cpu/int8)...")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    print("transcribing with word timestamps (this takes a few minutes)...")
    segments, info = model.transcribe(str(src), language="en",
                                      word_timestamps=True)
    words = [{"t": w.word.strip(), "start": float(w.start), "end": float(w.end)}
             for seg in segments for w in (seg.words or []) if w.word.strip()]
    if not words:
        print("ERROR: whisper produced no words")
        return 1

    out = dub.build_segments(
        words, marker, dub.MAX_SENTENCE_S,
        getattr(info, "language_probability", 0.0))
    project.write_json(dub.SEGMENTS, out)
    print(f"story window: {out['story_start']:.2f}s -> {out['story_end']:.2f}s "
          f"({len(out['segments'])} sentences)")
    if not out["marker_found"]:
        print("=" * 64)
        print(f"WARNING: story-end marker {marker!r} NOT found — used the WHOLE")
        print("transcript. If this source has a non-story tail (teaching/outro),")
        print("set the right phrase via --marker or project.yaml dub.story_end_marker,")
        print("or trim the story window with dub_refine_segments.py <slug> <first> <last>.")
        print("=" * 64)
    print(f"wrote {pdir / dub.SEGMENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
