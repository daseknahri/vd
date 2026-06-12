from fontTools.ttLib import TTFont
f = TTFont(r"assets/fonts/Tajawal-Bold.ttf")
cmap = f.getBestCmap()
# Presentation-form codepoints the legacy "simple shaper" would request:
tests = {
    "ALEF ISOLATED U+FE8D": 0xFE8D,        # boxed in render
    "ALEF FINAL U+FE8E": 0xFE8E,           # rendered OK in قا
    "WAW ISOLATED U+FEED": 0xFEED,         # boxed
    "WAW FINAL U+FEEE": 0xFEEE,            # rendered OK in لوسط
    "MEEM FINAL U+FEE2": 0xFEE2,           # boxed
    "MEEM MEDIAL U+FEE4": 0xFEE4,          # rendered OK
    "REH FINAL U+FEAE": 0xFEAE,            # boxed
    "TEH MARBUTA FINAL U+FE94": 0xFE94,    # boxed
    "BEH INITIAL U+FE91": 0xFE91,          # rendered OK
    "LAM-ALEF ISOLATED U+FEFB": 0xFEFB,
    "ALEF-HAMZA ISOLATED U+FE83": 0xFE83,  # boxed
}
for label, cp in tests.items():
    print(f"{label}: {'in cmap' if cp in cmap else 'NOT in cmap'}")
