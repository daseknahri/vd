"""Dub: render an English->Arabic review page from script.json.

Side-by-side table (timing, English scaffolding, Arabic narration, char count)
plus an ElevenLabs character/cost estimate (rate from config, so it tracks the
user's plan and matches run.py estimate), so the translation can be vetted
before any TTS spend. Writes projects/<slug>/dub_review.html.

  .venv\\Scripts\\python.exe scripts\\dub_review.py <slug>
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import contract, dub, voice  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="dub: EN->AR review page")
    ap.add_argument("slug")
    args = ap.parse_args()

    pdir = ROOT / "projects" / args.slug
    project = contract.Project(pdir)
    cfg = contract.load_config(pdir)
    rate = float((cfg.get("voice") or {}).get("usd_per_1k_chars", 0.30))

    try:
        script = project.script()
        segs = dub.load_segments(project)
    except contract.ContractError as exc:
        print(f"ERROR: {exc}")
        return 1
    en_by_id = {s["id"]: s for s in segs["segments"]}

    # Same char count the voice stage will bill (spoken text length).
    chars_by_id = dict(voice.scene_characters(script, project.pronunciation_overrides()))
    total_chars = sum(chars_by_id.values())
    cost = total_chars / 1000 * rate

    rows = []
    for sc in script["scenes"]:
        seg = en_by_id.get(sc["id"], {})
        start, end = seg.get("start", 0.0), seg.get("end", 0.0)
        rows.append(f"""
      <tr><td class="id">{sc['id']}</td>
        <td class="t">{_mmss(start)}<br><span class="dur">{end-start:.1f}s</span></td>
        <td class="en">{html.escape(seg.get('en',''))}</td>
        <td class="ar" dir="rtl">{html.escape(sc['narration_ar'])}</td>
        <td class="c">{chars_by_id.get(sc['id'], 0)}</td></tr>""")

    doc = f"""<!doctype html><html lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dub review — {html.escape(args.slug)}</title>
<style>
  body {{ font-family: system-ui, "Segoe UI", sans-serif; margin: 0;
         background: #14161c; color: #e6e8ee; }}
  header {{ padding: 20px 24px; border-bottom: 1px solid #2a2e39;
           position: sticky; top: 0; background: #14161c; }}
  h1 {{ margin: 0 0 6px; font-size: 18px; }}
  .stats {{ color: #9aa0ad; font-size: 14px; }} .stats b {{ color: #ffd479; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td {{ padding: 12px 14px; border-bottom: 1px solid #23262f; vertical-align: top; }}
  .id {{ color: #6b7280; width: 32px; }}
  .t {{ color: #8b93a3; font-size: 12px; white-space: nowrap; width: 64px; }}
  .dur {{ color: #5b6270; }}
  .en {{ color: #8b93a3; font-size: 14px; width: 38%; line-height: 1.5; }}
  .ar {{ font-size: 22px; line-height: 1.7; width: 46%; }}
  .c {{ color: #6b7280; font-size: 12px; text-align: right; }}
  tr:hover td {{ background: #191c24; }}
</style></head><body>
<header><h1>{html.escape(args.slug)} — Arabic dub translation review</h1>
  <div class="stats">{len(script['scenes'])} scenes &nbsp;·&nbsp;
    story {script['meta']['target_seconds']:.0f}s &nbsp;·&nbsp;
    <b>{total_chars:,}</b> billable chars &nbsp;·&nbsp;
    ElevenLabs est. <b>~${cost:.2f}</b>
    <span style="color:#5b6270">(@ ${rate:.2f}/1k, cold run)</span></div>
</header>
<table><tbody>{''.join(rows)}
</tbody></table></body></html>"""

    out = pdir / "dub_review.html"
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out}")
    print(f"scenes={len(script['scenes'])} total_chars={total_chars} "
          f"est_cost=${cost:.2f}")
    return 0


def _mmss(s: float) -> str:
    return f"{int(s)//60}:{int(s)%60:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
