"""Caption frame rendering — Pillow + libraqm, the ONLY Arabic shaping path.

Windows ffmpeg builds ship libass without HarfBuzz, so burning Arabic through
the `subtitles` filter mangles letter shaping (CLAUDE.md rule 3). This stage
therefore pre-renders every karaoke caption frame as a transparent PNG using
Pillow's RAQM layout engine (HarfBuzz + FriBiDi underneath); the render stage
only overlays PNGs and never shapes text itself.

Reads   script.json + timing.json
Writes  captions/cap_NNNN.png      one frame per display word (karaoke)
        captions/manifest.json     band geometry header + frame intervals
        captions.ass               export-only artifact (CapCut/humans) —
                                   never burned by libass
        captions_report.json       warnings (word-count mismatches etc.)
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Callable

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont, features

from pipeline import contract
from pipeline.errors import StageError

STAGE = "captions"

# Cross-stage names come from contract.py (single source of truth); the
# render stage reads the same constants.
CAPTIONS_DIR = contract.CAPTIONS_DIR
MANIFEST = contract.CAPTIONS_MANIFEST
REPORT = "captions_report.json"  # stage-private report
FRAME_NAME = "cap_{:04d}.png"

FONTS_DIR = contract.ROOT / "assets" / "fonts"

H_MARGIN = 80  # px each side; max line width = video width - 2 * H_MARGIN
DEFAULT_MAX_LINES = 2  # caption page height in lines (config: captions.max_lines)


# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------

def ass_color(value: str) -> tuple[int, int, int, int]:
    """ASS &HAABBGGRR / &H00BBGGRR string -> (R, G, B, A). ASS alpha 00 = opaque."""
    s = str(value).strip().rstrip("&")
    if s[:2].upper() == "&H":
        s = s[2:]
    if not 1 <= len(s) <= 8:
        raise contract.ContractError(f"bad ASS color {value!r}")
    try:
        n = int(s, 16)
    except ValueError:
        raise contract.ContractError(f"bad ASS color {value!r}") from None
    aa, bb, gg, rr = (n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF
    return (rr, gg, bb, 255 - aa)


def _ass_time(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _font_file(fonts_dir: Path, name: str) -> Path:
    """Resolve a family name from config to a font file via fontTools name
    tables. Captions want the heaviest standard cut, so 'Bold' wins when the
    family has several weights (Tajawal -> Tajawal-Bold.ttf)."""
    if not fonts_dir.is_dir():
        raise contract.ContractError(f"fonts directory missing: {fonts_dir}")
    families: dict[str, dict[str, Path]] = {}
    full_names: dict[str, Path] = {}
    for path in sorted(fonts_dir.iterdir()):
        if path.suffix.lower() not in {".ttf", ".otf"}:
            continue
        tt = TTFont(str(path), lazy=True)
        try:
            names = tt["name"]
            # 16/17 = typographic family/subfamily (set on non-RIBBI weights
            # like ExtraBold); fall back to legacy 1/2.
            family = (names.getDebugName(16) or names.getDebugName(1) or "").strip()
            sub = (names.getDebugName(17) or names.getDebugName(2) or "Regular").strip()
            full = (names.getDebugName(4) or f"{family} {sub}").strip()
        finally:
            tt.close()
        if family:
            families.setdefault(family.lower(), {}).setdefault(sub.lower(), path)
        full_names.setdefault(full.lower(), path)

    key = name.strip().lower()
    subs = families.get(key)
    if subs:
        for preferred in ("bold", "regular"):
            if preferred in subs:
                return subs[preferred]
        return next(iter(subs.values()))
    if key in full_names:  # allow exact full names like "Tajawal Bold"
        return full_names[key]
    raise contract.ContractError(
        f"caption font {name!r} not found in {fonts_dir} "
        f"(available families: {sorted(families)})"
    )


def _pair_words(narration: str, tscene: dict, warnings: list[dict]) -> list[dict]:
    """Display words (from script narration) + timing. 1:1 by index; on count
    mismatch fall back to distributing the scene interval proportionally to
    word length — warn, never crash (display text always wins)."""
    display = narration.split()
    twords = tscene.get("words") or []
    if len(display) == len(twords):
        return [
            {"text": d, "start": float(t["start"]), "end": float(t["end"])}
            for d, t in zip(display, twords)
        ]
    warnings.append({
        "scene": tscene["id"],
        "issue": "word count mismatch between narration and timing; "
                 "used proportional timing",
        "narration_words": len(display),
        "timing_words": len(twords),
    })
    start, end = float(tscene["start"]), float(tscene["end"])
    duration = end - start
    total = sum(len(w) for w in display) or 1
    out, acc = [], 0
    for w in display:
        s = start + duration * acc / total
        acc += len(w)
        out.append({"text": w, "start": s, "end": start + duration * acc / total})
    return out


def _paginate(words: list[dict], widths: list[float], max_w: float,
              space_w: float, max_lines: int) -> list[list[list[dict]]]:
    """Greedy RTL fill: pack words into lines (visual flow handled later by
    x-positioning), at most max_lines lines per page. Returns pages, each a
    list of lines, each a list of word dicts (narration order)."""
    pages: list[list[list[dict]]] = []
    page: list[list[dict]] = []
    line: list[dict] = []
    line_w = 0.0
    for word, w in zip(words, widths):
        fits = not line or line_w + space_w + w <= max_w
        if not fits:
            page.append(line)
            line, line_w = [], 0.0
            if len(page) == max_lines:
                pages.append(page)
                page = []
        line.append({**word, "width": w})
        line_w = w if len(line) == 1 else line_w + space_w + w
    if line:
        page.append(line)
    if page:
        pages.append(page)
    return pages


def _bidi_class(token: str) -> str:
    """'L' = contains a strong LTR char, 'R' = contains a strong RTL char
    (RTL wins for mixed tokens — raqm shapes inside the word), 'N' = neither
    (digits, punctuation)."""
    has_l = False
    for ch in token:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ("R", "AL"):
            return "R"
        if bidi == "L":
            has_l = True
    return "L" if has_l else "N"


def _visual_order(line: list[dict]) -> list[int]:
    """Word indices in right-to-left placement order.

    The line flows RTL, but per UAX#9 a run of consecutive LTR words
    ("New York", "iPhone 15") keeps left-to-right order WITHIN the run, so
    each maximal LTR run (strong-LTR words plus trailing neutral words such
    as digits) is reversed in the placement sequence."""
    order: list[int] = []
    i = 0
    while i < len(line):
        if _bidi_class(line[i]["text"]) == "L":
            j = i + 1
            while j < len(line) and _bidi_class(line[j]["text"]) in ("L", "N"):
                j += 1
            order.extend(reversed(range(i, j)))
            i = j
        else:
            order.append(i)
            i += 1
    return order


def _position(page: list[list[dict]], video_w: int, space_w: float,
              align: str = "right") -> list[dict]:
    """Assign x (left edge of each word) flowing right-to-left, and the line
    index. `align` "right" flows from the right margin (classic RTL); "center"
    centers each line on its full width so the words appear at their FINAL
    positions and never shift as a reveal builds. Embedded LTR runs keep their
    internal left-to-right order. Returns the page's words flattened, in
    narration (chronological) order."""
    flat: list[dict] = []
    for line_idx, line in enumerate(page):
        line_w = sum(w["width"] for w in line) + space_w * (len(line) - 1)
        if align == "center":
            x_right = (video_w + line_w) / 2.0
        else:
            x_right = float(video_w - H_MARGIN)
        for k in _visual_order(line):
            word = line[k]
            word["x"] = x_right - word["width"]
            word["line"] = line_idx
            x_right = word["x"] - space_w
        flat.extend(line)
    return flat


def _frame_times(page_words: list[dict]) -> list[tuple[float, float]]:
    """Karaoke intervals: each word holds until the next word starts, so the
    page never flickers off between words; last word holds to page end."""
    times = []
    for i, w in enumerate(page_words):
        end = page_words[i + 1]["start"] if i + 1 < len(page_words) else page_words[-1]["end"]
        times.append((w["start"], end))
    return times


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _render_frame(size: tuple[int, int], page_words: list[dict],
                  active: int | None, font: ImageFont.FreeTypeFont,
                  line_y: list[int], primary: tuple, highlight: tuple,
                  outline_rgba: tuple, outline_w: int) -> Image.Image:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, word in enumerate(page_words):
        # Each word is drawn separately so the active word can change color;
        # shaping is intra-word, so per-word draws keep Arabic joining intact.
        draw.text(
            (word["x"], line_y[word["line"]]),
            word["text"],
            font=font,
            fill=highlight if i == active else primary,
            direction="rtl",
            language="ar",
            stroke_width=outline_w,
            stroke_fill=outline_rgba,
        )
    return img


def _render_reveal_frame(size: tuple[int, int], page_words: list[dict],
                         upto: int, popping: bool, font: ImageFont.FreeTypeFont,
                         line_y: list[int], primary: tuple, pop: tuple,
                         outline_rgba: tuple, outline_w: int) -> Image.Image:
    """Kinetic-reveal frame: only the words spoken so far (0..upto) are drawn,
    at their fixed final positions, so the caption 'types on' word by word. The
    newest word (index upto) is drawn in `pop` colour while it is landing, then
    settles to `primary` — the grey->white pop the reference channel uses. Words
    drawn one at a time so raqm keeps Arabic joining intact."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i in range(upto + 1):
        word = page_words[i]
        draw.text(
            (word["x"], line_y[word["line"]]),
            word["text"],
            font=font,
            fill=pop if (popping and i == upto) else primary,
            direction="rtl",
            language="ar",
            stroke_width=outline_w,
            stroke_fill=outline_rgba,
        )
    return img


def _export_ass(path: Path, *, width: int, height: int, family: str,
                ccfg: dict, pages: list[tuple[float, float, list[str]]]) -> None:
    """Export-only .ass (one plain Dialogue per page, no karaoke tags) so a
    human can pull the captions into CapCut etc. NEVER burned via libass on
    Windows — its libass lacks HarfBuzz and breaks Arabic (CLAUDE.md rule 3)."""
    style = (
        f"Style: Caption,{family},{ccfg['font_size']},"
        f"{ccfg['primary_color']},{ccfg['highlight_color']},"
        f"{ccfg['outline_color']},&H00000000,-1,0,0,0,100,100,0,0,1,"
        f"{ccfg['outline']},0,2,{H_MARGIN},{H_MARGIN},{ccfg['margin_v']},1"
    )
    out = [
        "[Script Info]",
        "; Export-only portability artifact (CapCut / human editing).",
        "; NEVER burn this via libass/ffmpeg subtitles on Windows builds:",
        "; their libass lacks HarfBuzz and mangles Arabic shaping.",
        "; Burned captions come from captions/cap_*.png + captions/manifest.json.",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ]
    for start, end, lines in pages:
        text = "\\N".join(lines)
        out.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{text}"
        )
    # utf-8-sig: BOM is how CapCut/Aegisub detect UTF-8 in .ass files.
    path.write_text("\n".join(out) + "\n", encoding="utf-8-sig")


# --------------------------------------------------------------------------
# Stage entry point
# --------------------------------------------------------------------------

def run(project: contract.Project, cfg: dict, env: dict, *,
        force: bool = False) -> None:
    if not features.check("raqm"):
        raise StageError(
            STAGE,
            "Pillow was built without libraqm — Arabic would render unshaped. "
            "Reinstall pillow with raqm support.",
        )

    cap_dir = project.path(CAPTIONS_DIR)
    manifest_path = cap_dir / MANIFEST
    ass_path = project.path(contract.CAPTIONS)
    if manifest_path.exists() and ass_path.exists() and not force:
        return

    for name in (contract.SCRIPT, contract.TIMING):
        if not project.has(name):
            # A missing contracted input is a contract violation, not a
            # runtime failure (consistent with ingest/render).
            raise contract.ContractError(
                f"{name} missing — run earlier stages first"
            )
    script = project.script()
    timing = project.timing()

    try:
        vcfg, ccfg = cfg["video"], cfg["captions"]
        width, height = int(vcfg["width"]), int(vcfg["height"])
        font_name = str(ccfg["font"])
        font_size = int(ccfg["font_size"])
        primary = ass_color(ccfg["primary_color"])
        highlight = ass_color(ccfg["highlight_color"])
        outline_rgba = ass_color(ccfg["outline_color"])
        outline_w = int(ccfg["outline"])
        margin_v = int(ccfg["margin_v"])
        # style: "karaoke" (full line, active word highlighted — the default),
        # "static" (no per-word emphasis), or "reveal" (words type on one by one
        # with a pop on the newest — the kinetic look). `karaoke: false` still
        # selects "static" for back-compat.
        karaoke = bool(ccfg.get("karaoke", True))
        style = str(ccfg.get("style", "karaoke" if karaoke else "static")).strip().lower()
        align = str(ccfg.get("align", "center" if style == "reveal" else "right")).strip().lower()
        max_lines = max(1, int(ccfg.get("max_lines", DEFAULT_MAX_LINES)))
        pop_color = ass_color(ccfg["pop_color"]) if ccfg.get("pop_color") else (170, 170, 170, 255)
        pop_seconds = float(ccfg.get("pop_seconds", 0.12))
    except KeyError as e:
        raise contract.ContractError(f"config: missing video/captions key {e}") from e

    font = ImageFont.truetype(
        str(_font_file(FONTS_DIR, font_name)), font_size,
        layout_engine=ImageFont.Layout.RAQM,
    )
    measurer = ImageDraw.Draw(Image.new("RGBA", (4, 4)))

    def measure(text: str) -> float:
        return measurer.textlength(text, font=font, direction="rtl", language="ar")

    space_w = measure(" ")
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    line_gap = max(4, font_size // 4)
    pad = outline_w + 8
    band_h = max_lines * line_h + (max_lines - 1) * line_gap + 2 * pad
    line_y = [pad + i * (line_h + line_gap) for i in range(max_lines)]
    max_line_w = width - 2 * H_MARGIN

    cap_dir.mkdir(exist_ok=True)
    if force:
        # Invalidate the completion marker (manifest) BEFORE deleting any
        # frame: a crash mid-force must leave the stage looking incomplete
        # so a plain re-run rebuilds it, instead of no-opping over a
        # manifest that references deleted PNGs.
        manifest_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)
        for old in cap_dir.glob("cap_*.png"):
            old.unlink()

    timing_by_id = {s["id"]: s for s in timing["scenes"]}
    warnings: list[dict] = []
    frames: list[dict] = []
    ass_pages: list[tuple[float, float, list[str]]] = []
    n_png = 0

    for scene in sorted(script["scenes"], key=lambda s: s["id"]):
        tscene = timing_by_id.get(scene["id"])
        if tscene is None:
            raise contract.ContractError(
                f"timing.json has no scene id {scene['id']} — script and "
                f"timing are out of sync"
            )
        words = _pair_words(scene["narration_ar"], tscene, warnings)
        widths = [measure(w["text"]) for w in words]
        for w, ww in zip(words, widths):
            if ww > max_line_w:
                warnings.append({
                    "scene": scene["id"], "word": w["text"],
                    "issue": "word wider than caption line; will overflow margins",
                })

        for page in _paginate(words, widths, max_line_w, space_w, max_lines):
            flat = _position(page, width, space_w, align)
            page_start, page_end = flat[0]["start"], flat[-1]["end"]
            ass_pages.append((
                page_start, page_end,
                [" ".join(w["text"] for w in line) for line in page],
            ))
            page_idx = len(ass_pages) - 1

            # (start, end, render->Image) specs for this page's frames. `flat`
            # and page_idx are captured live — specs are consumed in this same
            # page iteration, below.
            specs: list[tuple[float, float, Callable[[], Image.Image]]] = []
            if style == "reveal":
                # Words type on one at a time; the newest lands in `pop_color`
                # for pop_seconds, then settles to primary.
                for i, (w_start, hold_end) in enumerate(_frame_times(flat)):
                    pop_end = min(w_start + pop_seconds, hold_end)
                    specs.append((w_start, pop_end, (lambda i=i: _render_reveal_frame(
                        (width, band_h), flat, i, True, font, line_y,
                        primary, pop_color, outline_rgba, outline_w))))
                    specs.append((pop_end, hold_end, (lambda i=i: _render_reveal_frame(
                        (width, band_h), flat, i, False, font, line_y,
                        primary, pop_color, outline_rgba, outline_w))))
            elif style == "karaoke":
                for i, (s, e) in enumerate(_frame_times(flat)):
                    specs.append((s, e, (lambda i=i: _render_frame(
                        (width, band_h), flat, i, font, line_y,
                        primary, highlight, outline_rgba, outline_w))))
            else:  # static: one frame, whole page, no per-word emphasis
                specs.append((page_start, page_end, (lambda: _render_frame(
                    (width, band_h), flat, None, font, line_y,
                    primary, highlight, outline_rgba, outline_w))))

            for start, end, render in specs:
                start_r, end_r = round(start, 3), round(end, 3)
                if end_r - start_r <= 0:
                    # Zero-length spans are contract-valid (align.py emits them
                    # when matched neighbors touch, and the reveal pop/settle
                    # split can collapse one side); the render stage's manifest
                    # validation rejects zero-duration frames, so skip them.
                    continue
                n_png += 1
                name = FRAME_NAME.format(n_png)
                render().save(cap_dir / name)
                frames.append({
                    "png": f"{CAPTIONS_DIR}/{name}",
                    "start": start_r,
                    "end": end_r,
                    "page": page_idx,
                })

    _export_ass(ass_path, width=width, height=height, family=font_name,
                ccfg=ccfg, pages=ass_pages)
    # Manifest is written last: it doubles as the stage's completion marker
    # for the idempotency check above.
    manifest = {
        "width": width,
        "band_height": band_h,
        "y": height - band_h - margin_v,
        "frames": frames,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    project.write_json(REPORT, {
        "warnings": warnings,
        "pages": len(ass_pages),
        "frames": len(frames),
    })
