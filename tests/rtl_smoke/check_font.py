from fontTools.ttLib import TTFont
import sys
for path in [r"assets/fonts/Tajawal-Bold.ttf", r"assets/fonts/Tajawal-Regular.ttf"]:
    f = TTFont(path)
    name = f["name"].getDebugName(4)
    cmap = f.getBestCmap()
    test = {"alef U+0627": 0x0627, "alef-hamza U+0623": 0x0623, "alef-hamza-below U+0625": 0x0625,
            "waw U+0648": 0x0648, "reh U+0631": 0x0631, "meem U+0645": 0x0645,
            "teh-marbuta U+0629": 0x0629, "lam U+0644": 0x0644, "beh U+0628": 0x0628,
            "arabic-1 U+0661": 0x0661, "hamza U+0621": 0x0621}
    print(f"== {name} | glyphs: {f['maxp'].numGlyphs} | cmap entries: {len(cmap)}")
    for label, cp in test.items():
        print(f"   {label}: {'YES' if cp in cmap else 'MISSING'}")
