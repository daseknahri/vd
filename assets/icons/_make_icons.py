"""Generate the small pop-in emphasis icons overlaid at emotional beats
(render stage). Bold, warm, storybook-friendly shapes with a soft white halo so
they read on any illustration. Run once: `python assets/icons/_make_icons.py`.
Outputs question.png / heart.png / sparkle.png (400x400 RGBA) beside this file.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONT = HERE.parent / "fonts" / "Tajawal-Bold.ttf"
S = 400
INK = (44, 42, 56, 255)          # dark storybook ink
RED = (206, 84, 84, 255)         # warm heart red
GOLD = (240, 190, 92, 255)       # warm sparkle gold


def _halo(base: Image.Image, grow: int = 22) -> Image.Image:
    """Return base composited over a soft white halo grown from its alpha."""
    a = base.split()[3]
    grown = a.filter(ImageFilter.MaxFilter(2 * (grow // 2) + 1))
    grown = grown.filter(ImageFilter.GaussianBlur(grow / 3))
    halo = Image.new("RGBA", base.size, (255, 255, 255, 0))
    halo.putalpha(grown)
    white = Image.new("RGBA", base.size, (255, 255, 255, 255))
    halo = Image.composite(white, Image.new("RGBA", base.size, (255, 255, 255, 0)), grown)
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    out = Image.alpha_composite(out, halo)
    out = Image.alpha_composite(out, base)
    return out


def _glyph(ch: str) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT), 300)
    d.text((S / 2, S / 2), ch, font=font, fill=INK, anchor="mm",
           stroke_width=10, stroke_fill=(255, 255, 255, 255))
    return _halo(img)


def _heart() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = []
    for i in range(361):
        t = math.radians(i)
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((S / 2 + x * 10.5, S / 2 - y * 10.5 - 10))
    d.polygon(pts, fill=RED, outline=INK, width=12)
    return _halo(img)


def _sparkle() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = S / 2
    R, r = 175, 55
    pts = []
    for k in range(8):
        ang = math.radians(k * 45 - 90)
        rad = R if k % 2 == 0 else r
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=GOLD, outline=INK, width=11)
    return _halo(img)


for name, im in (("question", _glyph("?")), ("heart", _heart()),
                 ("sparkle", _sparkle())):
    im.save(HERE / f"{name}.png")
    print("wrote", HERE / f"{name}.png")
