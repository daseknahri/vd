"""Dub step 2: dub_segments.json + dub_translations.json -> script.json.

Produces a contract-valid script.json (validate_script) whose scenes carry the
Arabic narration and each sentence's target_seconds = its source-video slot
duration. keywords/mood are placeholders required by the schema but unused by
the dub path (no footage stage runs). Idempotent: rewrites script.json.

  .venv\\Scripts\\python.exe scripts\\dub_build_script.py romeo-juliet-dub
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: dub_build_script.py <slug>")
        return 2
    slug = sys.argv[1]
    pdir = ROOT / "projects" / slug
    segs = json.loads((pdir / "dub_segments.json").read_text(encoding="utf-8"))
    tr = json.loads((pdir / "dub_translations.json").read_text(encoding="utf-8"))
    translations = tr["translations"]

    scenes = []
    for s in segs["segments"]:
        ar = translations.get(str(s["id"]))
        if not ar or not ar.strip():
            print(f"ERROR: no translation for segment {s['id']}")
            return 1
        scenes.append({
            "id": s["id"],
            "narration_ar": ar.strip(),
            # placeholders: the dub path never runs footage; schema needs them
            "keywords": [["romeo and juliet"]],
            "mood": "calm",
            "target_seconds": round(s["end"] - s["start"], 3),
        })

    src_url = ""
    surl = pdir / "source_url.txt"
    if surl.exists():
        src_url = surl.read_text(encoding="utf-8").strip()

    script = {
        "meta": {
            "source_url": src_url or "https://www.youtube.com/watch?v=J5Vn7kCoPvE",
            "audience": "general Arab",
            "dialect": tr.get("dialect", "MSA"),
            "target_seconds": round(segs["story_end"] - segs["story_start"], 3),
            "workflow": "dub",
        },
        "hook": scenes[0]["narration_ar"],
        "scenes": scenes,
        "post": {
            "title": "روميو وجولييت — قصة قصيرة",
            "description": "قصة روميو وجولييت بالعربية.",
            "hashtags": ["#قصص", "#روميو_وجولييت"],
        },
    }
    contract.validate_script(script)
    out = pdir / "script.json"
    out.write_text(json.dumps(script, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"wrote {out} : {len(scenes)} scenes, "
          f"story {script['meta']['target_seconds']:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
