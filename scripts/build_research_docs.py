"""Regenerate docs/ai-video/01..07 from an ai-video-field-research workflow run.

The `ai-video-field-research` workflow returns one structured result per domain;
this renders each into a markdown file. Point it at that run's journal.jsonl
(printed in the workflow's transcript dir) — results are keyed by `domain`, so
completion order doesn't matter.

  .venv\\Scripts\\python.exe scripts\\build_research_docs.py <path-to-journal.jsonl>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "ai-video"

# domain key -> (filename, human title), in reading order
META = [
    ("text-and-image-to-video-models", "01-generation-models.md",
     "Video generation models (text/image-to-video)"),
    ("voice-tts-dubbing-lipsync", "02-voice-tts-dubbing-lipsync.md",
     "Voice: TTS, dubbing & lipsync"),
    ("captions-subtitles-rtl-arabic", "03-captions-subtitles-rtl-arabic.md",
     "Captions, subtitles & Arabic RTL"),
    ("editing-automation-mcp", "04-editing-automation-mcp.md",
     "Editing, automation & MCP servers"),
    ("faceless-automation-publishing", "05-faceless-automation-publishing.md",
     "Faceless automation & publishing"),
    ("open-source-selfhosted-stack", "06-open-source-selfhosted.md",
     "Open-source / self-hosted stack"),
    ("workflow-mapping-and-recommendations", "07-recommendations.md",
     "Recommendations for the video factory"),
]

DISCLAIMER = (
    "> **Research snapshot.** Compiled by a web-research sweep for the "
    "video-factory project. This is a fast-moving field: prices, versions and "
    "availability change monthly. Treat specifics as *leads to verify*, not "
    "gospel — follow the sources. Re-run the `ai-video-field-research` workflow "
    "to refresh.\n"
)


def _cell(s: object) -> str:
    return re.sub(r"\s*\|\s*", " / ", str(s or "").replace("\n", " ")).strip()


def render(d: dict, title: str) -> str:
    if not d:
        return f"# {title}\n\n{DISCLAIMER}\n\n_(no result for this domain)_\n"
    lines = [f"# {title}", "", DISCLAIMER, "## Summary", "",
             d.get("summary", ""), ""]
    tools = d.get("tools") or []
    if tools:
        lines += ["## Tools & models", "",
                  "| Name | Category | Access | Pricing | Notable capability |",
                  "|------|----------|--------|---------|--------------------|"]
        for t in tools:
            name, url = t.get("name", ""), t.get("url")
            name_cell = f"[{_cell(name)}]({url})" if url else _cell(name)
            lines.append(
                f"| {name_cell} | {_cell(t.get('category'))} | "
                f"{_cell(t.get('access'))} | {_cell(t.get('pricing', 'unknown'))} | "
                f"{_cell(t.get('capability'))} |")
        lines.append("")
    if d.get("key_facts"):
        lines += ["## Key facts (as researched)", ""]
        lines += [f"- {f}" for f in d["key_facts"]] + [""]
    if d.get("relevance_to_video_factory"):
        lines += ["## Relevance to the video factory", "",
                  d["relevance_to_video_factory"], ""]
    if d.get("watch_list"):
        lines += ["## Watch list", ""] + [f"- {w}" for w in d["watch_list"]] + [""]
    if d.get("sources"):
        lines += ["## Sources", ""] + [f"- <{s}>" for s in d["sources"]] + [""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="regenerate docs/ai-video from a journal")
    ap.add_argument("journal", help="path to the workflow run's journal.jsonl")
    args = ap.parse_args()

    by_domain: dict[str, dict] = {}
    for line in Path(args.journal).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("type") != "result":
            continue
        val = obj.get("value") or obj.get("result")
        if isinstance(val, dict) and val.get("domain"):
            by_domain[val["domain"]] = val

    DOCS.mkdir(parents=True, exist_ok=True)
    written = 0
    for key, fname, title in META:
        (DOCS / fname).write_text(render(by_domain.get(key, {}), title),
                                  encoding="utf-8")
        written += 1
        if key not in by_domain:
            print(f"  WARN: no result for domain {key!r}")
    print(f"wrote {written} docs to {DOCS} "
          f"(README.md is hand-curated — not regenerated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
