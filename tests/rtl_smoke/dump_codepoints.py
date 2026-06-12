"""Dump non-ASCII codepoints of each Dialogue line in test.ass."""
import io
import unicodedata

with io.open(r"tests/rtl_smoke/test.ass", encoding="utf-8") as f:
    for n, line in enumerate(f, 1):
        if not line.startswith("Dialogue"):
            continue
        text = line.rsplit(",,0,0,0,", 1)[-1].strip()
        print(f"line {n}:")
        for ch in text:
            if ord(ch) > 0x7F:
                try:
                    name = unicodedata.name(ch)
                except ValueError:
                    name = "<unnamed>"
                print(f"  U+{ord(ch):04X} {name}")
        print()
