import io
with io.open(r"tests/rtl_smoke/test.ass", encoding="utf-8") as f:
    for line in f:
        if "Dialogue" in line and ("لا" in line or "FEFB" in line):
            for ch in line:
                if ord(ch) > 0x2000:
                    print(f"U+{ord(ch):04X}", end=" ")
            print()
