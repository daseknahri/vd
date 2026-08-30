"""Dub step 2: segments + dub_translations.json -> script.json.

Produces a contract-valid script.json (validate_script) whose scenes carry the
Arabic narration and each sentence's target_seconds = its source-video slot.
Post metadata / dialect / source_url all come from the translations file or
source_url.txt — nothing about a specific video is hardcoded, so any dub project
builds correct meta/post. Consumes the refined segments if present, else raw.

  .venv\\Scripts\\python.exe scripts\\dub_build_script.py <slug>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract, dub  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="dub step 2: build script.json")
    ap.add_argument("slug")
    args = ap.parse_args()

    pdir = ROOT / "projects" / args.slug
    project = contract.Project(pdir)
    src_url = ""
    if project.has(contract.SOURCE_URL):
        src_url = project.read_text(contract.SOURCE_URL).strip()

    try:
        segs = dub.load_segments(project)
        if not project.has(dub.TRANSLATIONS):
            raise contract.ContractError(
                f"{dub.TRANSLATIONS} not found — write the Arabic translations first")
        translations = project.read_json(dub.TRANSLATIONS)
        script = dub.build_script(segs, translations, src_url)
    except contract.ContractError as exc:
        print(f"ERROR: {exc}")
        return 1

    project.write_json(contract.SCRIPT, script)
    print(f"wrote {pdir / contract.SCRIPT} : {len(script['scenes'])} scenes, "
          f"story {script['meta']['target_seconds']:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
