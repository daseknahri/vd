"""RTL smoke test via Pillow + libraqm (HarfBuzz shaping).

Renders the same three Arabic test lines that exposed the libass
simple-shaper problem. Pass = connected letters, correct RTL order,
no tofu boxes, correct bidi for embedded Latin and digits.
"""
from PIL import Image, ImageDraw, ImageFont, features

assert features.check("raqm"), "Pillow built without raqm — cannot shape Arabic"

W, H = 1080, 1920
img = Image.new("RGBA", (W, H), (26, 26, 46, 255))
draw = ImageDraw.Draw(img)

font = ImageFont.truetype(
    r"assets/fonts/Tajawal-Bold.ttf", 80, layout_engine=ImageFont.Layout.RAQM
)

lines = [
    "القراءة من اليمين إلى اليسار",
    "تجربة الحروف المتصلة واللام ألف: لا، السلام",
    "أرقام ١٢٣ وكلمة RTL في الوسط",
]

y = 700
for text in lines:
    draw.text(
        (W // 2, y), text, font=font, fill=(255, 255, 255, 255),
        anchor="mm", direction="rtl", language="ar",
        stroke_width=4, stroke_fill=(0, 0, 0, 255),
    )
    y += 300

img.convert("RGB").save(r"tests/rtl_smoke/rtl_pillow.png")
print("saved tests/rtl_smoke/rtl_pillow.png")
