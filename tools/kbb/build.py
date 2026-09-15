"""Build the Korean ROM.

Expansion layout (ROM grows from 1.5 MB to 2 MB, LoROM):
  0x180000  bank $30 ($B0): script bank (12 tables, new encoding)
  0x188000  bank $31 ($B1): renderer code (asm/text.s); glyph widths at $B1:9000
  0x190000  bank $32 ($B2) ...: glyph bitmaps, 32 bytes each, 1024 per bank

Usage: python -m tools.kbb.build ORIGINAL.sfc OUTPUT.sfc [--csv translations/strings.csv]
"""
import csv
import hashlib
import os
import struct
import subprocess
import sys
import tempfile

from tools.kbb import encode, glyphs, script, text
from tools.kbb import labels as L

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORIGINAL_MD5 = "42e27da8a2b91eca749d9700ebccd865"
ROM_SIZE = 0x200000
SCRIPT_ROM = 0x180000
CODE_ROM = 0x188000
WIDTHS_ROM = CODE_ROM + 0x1000
WIDTHS_LIMIT = 0x3000
GLYPH_ROM = 0x190000
GLYPHS_PER_BANK = 0x400
ASM_SOURCE = os.path.join(ROOT, "tools", "kbb", "asm", "text.s")
ASM_CONFIG = os.path.join(ROOT, "tools", "kbb", "asm", "bank.cfg")
CC65_BIN = os.environ.get("CC65_BIN", "")

CODE_ENTRY = 0xB18000
ENTRY_START, ENTRY_MAIN, ENTRY_NESTED, ENTRY_NMI, ENTRY_LABEL = (CODE_ENTRY + 4 * k for k in range(5))
LABEL_TABLE_ROM = CODE_ROM + 0x4000          # $B1:C000, u16 string offsets then strings
RESERVED_ROM = CODE_ROM + 0x3F00             # $B1:BF00, 64-byte bitmap of kanji tiles to keep
# 16x16 glyphs drawn by screens whose data is not located yet (versus title, pre-game menu)
RESERVED_GLYPHS = "熱血野球大会対先発火小変更打順守備選手デタ"
LABEL_TABLE_LIMIT = 0x4000
LABEL_MARK_TOP, LABEL_MARK_BOTTOM = 0xC000, 0xD000
ROW_WRITER_ROM = 0x08B390

WIDE_PX = 248          # dialogue window: columns 1..31
MENU_PX = 208          # menu message window: columns 6..31
HEADER_CHECKSUM = 0x7FDE
HEADER_COMPLEMENT = 0x7FDC


class BuildError(Exception):
    pass


def jml(addr):
    return bytes([0x5C, addr & 0xFF, (addr >> 8) & 0xFF, addr >> 16])


def patches(table_addr):
    """[(rom offset, original bytes, new bytes)]"""
    def lo16(v):
        return struct.pack("<H", v)
    return [
        (0x0869FA, b"\xA9\x86", b"\xA9\xB0"),                                      # data bank -> script bank
        (0x086A05, b"\xB9\x22\x9A", b"\xB9" + lo16(table_addr["story"])),         # story pointer table
        (0x086AFC, b"\xA9\x18\x80", b"\xA9" + lo16(table_addr["surname"])),       # var 42: surname
        (0x086B1C, b"\xA9\xD5\x87", b"\xA9" + lo16(table_addr["name_extra2"])),   # var 43
        (0x086B5C, b"\xA9\x27\x8A", b"\xA9" + lo16(table_addr["item"])),          # var 45/59: item
        (0x086B7B, b"\xA9\xA2\x99", b"\xA9" + lo16(table_addr["school"])),        # var 46: school
        (0x086A21, b"\xA5\x02\x85\x06", jml(ENTRY_START)),                        # message start
        (0x086A2B, b"\xA5\x10\x8F\x2B\x2F\x7E", jml(ENTRY_MAIN) + b"\xEA\xEA"),   # main loop head
        (0x086BF7, b"\xA5\x10\x8F\x2B\x2F\x7E", jml(ENTRY_NESTED) + b"\xEA\xEA"), # nested loop head
        (0x007F0C, b"\xB1\xF6\x80", struct.pack("<I", ENTRY_NMI)[:3]),            # NMI vector
        (ROW_WRITER_ROM, b"\x08\x8B\x0B\xC2\x30", jml(ENTRY_LABEL) + b"\xEA"),     # label row writer
    ]


def apply_patches(rom, plist):
    for off, old, new in plist:
        if bytes(rom[off:off + len(old)]) != old:
            raise BuildError("unexpected bytes at %06X: %s" % (off, rom[off:off + len(old)].hex()))
        assert len(new) == len(old)
        rom[off:off + len(new)] = new


def assemble():
    with tempfile.TemporaryDirectory() as tmp:
        obj = os.path.join(tmp, "text.o")
        out = os.path.join(tmp, "text.bin")
        subprocess.run([os.path.join(CC65_BIN, "ca65"), "--cpu", "65816", "-o", obj, ASM_SOURCE], check=True)
        subprocess.run([os.path.join(CC65_BIN, "ld65"), "-C", ASM_CONFIG, "-o", out, obj], check=True)
        return open(out, "rb").read()


def checksum(rom):
    return sum(rom) & 0xFFFF


def fix_checksum(rom):
    struct.pack_into("<HH", rom, HEADER_COMPLEMENT, 0xFFFF, 0x0000)
    c = checksum(rom)
    struct.pack_into("<HH", rom, HEADER_COMPLEMENT, c ^ 0xFFFF, c)


def load_texts(rom, csv_path):
    """({id: text}, set of translated ids): the Korean column when present,
    otherwise the extracted Japanese."""
    texts = {r["id"]: r["japanese"] for r in text.extract(rom)}
    korean = set()
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("korean"):
                    texts[r["id"]] = r["korean"]
                    korean.add(r["id"])
    return texts, korean


def load_labels(csv_path):
    """Rows of labels.csv that carry a Korean text."""
    if not csv_path or not os.path.exists(csv_path):
        return []
    with open(csv_path, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("korean")]


def label_table(rows, gs):
    """Bytes for $B1:C000: u16 SNES offsets (bank $B1) per id, then the encoded strings."""
    ptrs = bytearray()
    strings = bytearray()
    base = 0xC000 + 2 * len(rows)
    for r in rows:
        ptrs += struct.pack("<H", base + len(strings))
        strings += gs.encode(r["korean"].replace("\n", " "))
    data = bytes(ptrs + strings)
    if len(data) > LABEL_TABLE_LIMIT:
        raise BuildError("label table overflow")
    return data


def mark_labels(rom, rows):
    """Overwrite each translated row pair with marker words (see asm/text.s)."""
    for lid, r in enumerate(rows):
        bank, n = int(r["bank"], 16), int(r["n"])
        for key, mark in (("top", LABEL_MARK_TOP), ("bottom", LABEL_MARK_BOTTOM)):
            off = bank * 0x8000 + int(r[key], 16) - 0x8000
            rom[off:off + 2 * n] = struct.pack("<H", mark | lid) + b"\x00\x00" * (n - 1)


def reserved_bitmap(rom, all_rows, translated):
    """Kanji-area tiles (0x100-0x2FF) that untranslated labels still draw, as 512 bits."""
    from tools.kbb.kanji16 import KANJI16
    done = {r["id"] for r in translated}
    tiles = set()
    for r in all_rows:
        if r["id"] in done:
            continue
        bank, n = int(r["bank"], 16), int(r["n"])
        for key in ("top", "bottom"):
            off = bank * 0x8000 + int(r[key], 16) - 0x8000
            for w in struct.unpack_from("<%dH" % n, rom, off):
                tiles.add(w & 0x3FF)
    for ch in RESERVED_GLYPHS:
        k = KANJI16.index(ch)
        tl = 0x100 + (k // 8) * 0x20 + (k % 8) * 2
        tiles.update((tl, tl + 1, tl + 0x10, tl + 0x11))
    bits = bytearray(64)
    for t in tiles:
        if 0x100 <= t < 0x300:
            bits[(t - 0x100) >> 3] |= 1 << ((t - 0x100) & 7)
    return bytes(bits)


def build(original, csv_path=None, labels_csv=None, log=print):
    if hashlib.md5(original).hexdigest() != ORIGINAL_MD5:
        raise BuildError("original ROM md5 mismatch")
    rom = bytearray(original) + b"\xFF" * (ROM_SIZE - len(original))
    texts, korean_ids = load_texts(original, csv_path)
    label_rows = load_labels(labels_csv)
    gs = encode.GlyphSet(list(texts.values()) + [r["korean"] for r in label_rows])
    encoded = {k: gs.encode(v) for k, v in texts.items()}
    bank, table_addr = script.build_bank(original, encoded)
    widths, bitmaps = gs.bitmaps()
    width_of = {ch: widths[idx] for ch, idx in gs.index.items()}
    translated = {k: v for k, v in texts.items() if k in korean_ids}
    for sid, lines in encode.check(translated, width_of, max_px=WIDE_PX):
        log("overflow (>2 lines at %dpx): %s -> %s" % (WIDE_PX, sid, [l for l, _ in lines]))
    for sid, lines in encode.check({k: v for k, v in translated.items() if k.startswith("story_")},
                                   width_of, max_px=MENU_PX):
        log("note (>2 lines in the %dpx menu window): %s" % (MENU_PX, sid))
    if gs.missing:
        log("glyphs missing from the font, drawn as '?': %s" % "".join(sorted(gs.missing)))
    if len(widths) > WIDTHS_LIMIT:
        raise BuildError("too many glyphs for the width table")
    if GLYPH_ROM + len(bitmaps) > ROM_SIZE:
        raise BuildError("glyph bitmaps do not fit")
    for r in label_rows:
        px = sum(width_of.get(c, 12) if c != " " else encode.SPACE_W for c in r["korean"])
        if px > int(r["n"]) * 8:
            log("label too wide (%dpx > %dpx): %s %s" % (px, int(r["n"]) * 8, r["id"], r["korean"]))
    code = assemble()
    ltab = label_table(label_rows, gs)
    rom[LABEL_TABLE_ROM:LABEL_TABLE_ROM + len(ltab)] = ltab
    rom[RESERVED_ROM:RESERVED_ROM + 64] = reserved_bitmap(original, L.extract(original), label_rows)
    mark_labels(rom, label_rows)
    rom[SCRIPT_ROM:SCRIPT_ROM + len(bank)] = bank
    rom[CODE_ROM:CODE_ROM + len(code)] = code
    rom[WIDTHS_ROM:WIDTHS_ROM + len(widths)] = widths
    rom[GLYPH_ROM:GLYPH_ROM + len(bitmaps)] = bitmaps
    apply_patches(rom, patches(table_addr))
    fix_checksum(rom)
    used = len(bank.rstrip(b"\xff"))
    log("script bank: %d/%d bytes, glyphs: %d (%d one-byte), code: %d bytes, labels: %d"
        % (used, script.BANK_SIZE, gs.count, min(gs.count, 0x80) - 3, len(code.rstrip(b"\xff")), len(label_rows)))
    return bytes(rom), gs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    csv_path = os.path.join(ROOT, "translations", "strings.csv")
    labels_csv = os.path.join(ROOT, "translations", "labels.csv")
    if "--csv" in sys.argv:
        csv_path = sys.argv[sys.argv.index("--csv") + 1]
    original = open(args[0], "rb").read()
    rom, _ = build(original, csv_path, labels_csv)
    open(args[1], "wb").write(rom)
    print("wrote", args[1], len(rom), "bytes")


if __name__ == "__main__":
    main()
