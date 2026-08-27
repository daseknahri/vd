"""Dub step 1: source video -> timed English sentences (research/timing only).

Runs faster-whisper on the source audio with word timestamps, isolates the
story window, and groups words into caption-sized sentences with precise
(start, end) times. Output feeds the translation step; NOTHING here is copied
into the final video's audio or text — the English is timing scaffolding only.

Writes projects/<slug>/dub_segments.json:
  {"story_start": float, "story_end": float,
   "segments": [{"id", "start", "end", "en"}]}

Console output stays ASCII (CLAUDE.md rule 4). Run from repo root:
  .venv\\Scripts\\python.exe scripts\\dub_segment.py romeo-juliet-dub
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Phrase that marks the end of the narrated story (the teaching section
# begins right after it). Matched on a lowercased, punctuation-stripped
# rolling window of whisper words.
STORY_END_MARKER = "now let s do some shadowing"
# Max spoken seconds per caption sentence before we force a split on the
# nearest sentence punctuation; keeps captions to ~1-2 lines.
MAX_SENTENCE_S = 7.0


def _norm(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum() or c.isspace()).strip()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: dub_segment.py <project-slug>")
        return 2
    slug = sys.argv[1]
    pdir = ROOT / "projects" / slug
    src = pdir / "source.mp4"
    if not src.exists():
        print(f"ERROR: {src} not found")
        return 1

    from faster_whisper import WhisperModel

    print("loading whisper (small, cpu/int8)...")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    print("transcribing with word timestamps (this takes a few minutes)...")
    segments, info = model.transcribe(
        str(src), language="en", word_timestamps=True,
    )

    # Flatten to a word stream with times; also keep segment-level sentence
    # boundaries (whisper puts punctuation on the last word of a clause).
    words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if not text:
                continue
            words.append({"t": text, "start": float(w.start),
                          "end": float(w.end)})

    if not words:
        print("ERROR: whisper produced no words")
        return 1

    # Locate the story-end marker on a rolling normalized window.
    story_end_idx = len(words)
    norm_words = [_norm(w["t"]) for w in words]
    marker_tokens = STORY_END_MARKER.split()
    for i in range(len(norm_words) - len(marker_tokens) + 1):
        window = " ".join(norm_words[i:i + len(marker_tokens)]).split()
        if window == marker_tokens:
            story_end_idx = i
            break
    story_words = words[:story_end_idx]
    story_start = story_words[0]["start"]
    story_end = story_words[-1]["end"]
    print(f"story window: {story_start:.2f}s -> {story_end:.2f}s "
          f"({len(story_words)} words; marker "
          f"{'found' if story_end_idx < len(words) else 'NOT found -> used full'})")

    # Group words into sentences: break after a word ending in .?! or when
    # the running sentence exceeds MAX_SENTENCE_S.
    segs: list[dict] = []
    cur: list[dict] = []
    cur_start = story_words[0]["start"]
    for w in story_words:
        cur.append(w)
        ends_sentence = w["t"].rstrip()[-1:] in ".?!"
        too_long = (w["end"] - cur_start) >= MAX_SENTENCE_S
        if ends_sentence or too_long:
            segs.append({
                "id": len(segs) + 1,
                "start": round(cur_start, 3),
                "end": round(w["end"], 3),
                "en": " ".join(x["t"] for x in cur).strip(),
            })
            cur = []
            if w is not story_words[-1]:
                cur_start = w["end"]
    if cur:
        segs.append({
            "id": len(segs) + 1,
            "start": round(cur_start, 3),
            "end": round(cur[-1]["end"], 3),
            "en": " ".join(x["t"] for x in cur).strip(),
        })

    out = {
        "story_start": round(story_start, 3),
        "story_end": round(story_end, 3),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 3),
        "segments": segs,
    }
    out_path = pdir / "dub_segments.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"wrote {out_path} : {len(segs)} sentences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
