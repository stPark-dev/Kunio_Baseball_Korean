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

from tools.kbb import bg2, encode, font8, glyphs, grid, ingame, script, text
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
GLYPH8_ROM = 0x198000                        # $B3:8000, 16 bytes per glyph id (8x8 Korean)
INGAME_FONT_ROM = 0x19B000                   # $B3:B000, 4 KB font block for the match screens
INGAME_FONT_SITE = 0x0067D9                  # source address bytes of the in-game font DMA descriptor (cmd 1C)
# cmd 06 descriptors "06 bank size16 src16 vram16" that load the 8x8 font to VRAM $C000 during matches
INGAME_FONT_SITES06 = (0x000E57, 0x0016B4, 0x0017FE, 0x00190E)
POOL8_ROM = CODE_ROM + 0x3E00                # $B1:BE00: u16 count, then dynamic 8x8 slot numbers
ASM_SOURCE = os.path.join(ROOT, "tools", "kbb", "asm", "text.s")
ASM_CONFIG = os.path.join(ROOT, "tools", "kbb", "asm", "bank.cfg")
CC65_BIN = os.environ.get("CC65_BIN", "")

CODE_ENTRY = 0xB18000
(ENTRY_START, ENTRY_MAIN, ENTRY_NESTED, ENTRY_NMI, ENTRY_LABEL,
 ENTRY_GAME_START, ENTRY_GAME_MAIN, ENTRY_GAME_NESTED, ENTRY_HUD_NAME) = (CODE_ENTRY + 4 * k for k in range(9))
GAME_PX = 176          # in-game commentary window: 22 columns
# The in-game hooks work in isolation but every byte of VRAM is in use during a match
# (BG1 has a 64x64 tilemap at $E000-$FFFF), so there is no room for the glyph cache yet.
# Keep the original Japanese commentary until an in-game font plan exists (see README).
GAME_TEXT = True
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


def patches(table_addr, game_text=GAME_TEXT):
    """[(rom offset, original bytes, new bytes)]"""
    def lo16(v):
        return struct.pack("<H", v)
    base = [
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
    game = [
        # in-game commentary renderer (bank $04): script bank + hooks
        (0x024AF4, b"\xA9\x86\x86", b"\xA9\xB0\xB0"),
        (0x024B04, b"\xAF\x0E\x80\x86", b"\xAF\x0E\x80\xB0"),
        (0x024B21, b"\xAF\x0E\x80\x86", b"\xAF\x0E\x80\xB0"),
        (0x024B34, b"\xAA\x82\xFF\x00", jml(ENTRY_GAME_START)),
        (0x024B4A, b"\xAF\x36\x69\x7E", jml(ENTRY_GAME_NESTED)),
        (0x024BD2, b"\xA9\x86\x86", b"\xA9\xB0\xB0"),
        (0x024C37, b"\xAF\x33\x69\x7E", jml(ENTRY_GAME_MAIN)),
        (0x024C7A, b"\xAF\x10\x80\x86", b"\xAF\x10\x80\xB0"),
        (0x024C81, b"\xA9\x86\x86", b"\xA9\xB0\xB0"),
        (0x024CAC, b"\x6F\x00\x80\x86", b"\x6F\x00\x80\xB0"),
        (0x024CCB, b"\x6F\x16\x80\x86", b"\x6F\x16\x80\xB0"),
        (0x024CEA, b"\x6F\x0C\x80\x86", b"\x6F\x0C\x80\xB0"),
        (0x024DA4, b"\xAF\x36\x69\x7E", jml(ENTRY_GAME_NESTED)),
        (0x024E2C, b"\xA9\x86\x86", b"\xA9\xB0\xB0"),
        (0x024F09, b"\xA9\x86\x86", b"\xA9\xB0\xB0"),
        # HUD player names (bank $0E)
        (0x0777B2, b"\xA5\x22\x0A\xAA", jml(ENTRY_HUD_NAME)),
    ]
    return base + (game if game_text else [])


def apply_patches(rom, plist):
    for off, old, new in plist:
        if bytes(rom[off:off + len(old)]) != old:
            raise BuildError("unexpected bytes at %06X: %s" % (off, rom[off:off + len(old)].hex()))
        assert len(new) == len(old)
        rom[off:off + len(new)] = new


def assemble(defines=()):
    with tempfile.TemporaryDirectory() as tmp:
        obj = os.path.join(tmp, "text.o")
        out = os.path.join(tmp, "text.bin")
        flags = ["-D%s=%d" % kv for kv in defines]
        subprocess.run([os.path.join(CC65_BIN, "ca65"), "--cpu", "65816"] + flags + ["-o", obj, ASM_SOURCE], check=True)
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


def reserved_bitmap(rom, all_rows, translated, extra=()):
    """Kanji-area tiles (0x100-0x2FF) that untranslated labels still draw, as 512 bits."""
    from tools.kbb.kanji16 import KANJI16
    done = {r["id"] for r in translated}
    tiles = set(extra)
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


def korean_kanji16(rom):
    """Draw Korean syllables over the 16x16 kanji glyphs listed in kanji16.KOREAN16 (in place)."""
    from tools.kbb import font, glyphs
    from tools.kbb.kanji16 import KANJI16, KOREAN16
    for ch, ko in KOREAN16.items():
        dw, cell = glyphs.render(ko)
        shift = (16 - dw) // 2
        px = [[3 if (v >> shift) & (0x8000 >> x) else 0 for x in range(16)] for v in cell]
        for n in (i for i, c in enumerate(KANJI16) if c == ch):
            tl = 0x100 + (n // 8) * 0x20 + (n % 8) * 2
            for t, (ox, oy) in zip((tl, tl + 1, tl + 0x10, tl + 0x11), ((0, 0), (8, 0), (0, 8), (8, 8))):
                off = font.FONT_OFFSET + t * font.TILE_BYTES
                rom[off:off + font.TILE_BYTES] = font.encode_tile([r[ox:ox + 8] for r in px[oy:oy + 8]])


def load_ingame(csv_path):
    if not csv_path or not os.path.exists(csv_path):
        return []
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ingame_font(original, rows):
    """(font block, static {char: tile}, pool tiles) for the match screens."""
    chars = sorted({c for r in rows for c in r.get("korean", "") if "가" <= c <= "힣"})
    if len(chars) > len(font8.FREE) - 64:
        raise BuildError("too many static in-game syllables: %d" % len(chars))
    static = dict(zip(chars, font8.FREE))
    block, pool = font8.build_block(original[0x0B47E5:0x0B47E5 + 0x1000], static)
    return block, static, pool


def glyph8_table(gs):
    """16 bytes per glyph id, Galmuri7 8x8 rendering of the same character set."""
    out = bytearray(gs.count * 16)
    missing = font8.tile8("?")
    for ch, idx in gs.index.items():
        out[idx * 16:(idx + 1) * 16] = font8.tile8(ch) or missing
    return bytes(out)


def build(original, csv_path=None, labels_csv=None, ingame_csv=None, teams_csv=None, bg2_csv=None, log=print):
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
    game_ids = {"story_%03d" % k for k in list(range(130, 334)) + list(range(687, 694))}
    for sid, lines in encode.check({k: v for k, v in translated.items() if k in game_ids},
                                   width_of, max_px=GAME_PX):
        log("overflow (>2 lines in the %dpx game window): %s -> %s" % (GAME_PX, sid, [l for l, _ in lines]))
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
    code = assemble([("SURNAME_TABLE", table_addr["surname"])])
    ingame_rows = load_ingame(ingame_csv)
    if ingame_rows:
        block, static, pool = ingame_font(original, ingame_rows)
        rom[INGAME_FONT_ROM:INGAME_FONT_ROM + len(block)] = block
        snes = 0x800000 | (INGAME_FONT_ROM // 0x8000 << 16) | 0x8000 | (INGAME_FONT_ROM % 0x8000)
        rom[INGAME_FONT_SITE:INGAME_FONT_SITE + 3] = struct.pack("<I", snes)[:3]
        for site in INGAME_FONT_SITES06:
            if bytes(rom[site:site + 8]) != b"\x06\x96\x00\x10\xE5\xC7\x00\x60":
                raise BuildError("unexpected font descriptor at %06X" % site)
            rom[site + 1] = snes >> 16
            struct.pack_into("<H", rom, site + 4, snes & 0xFFFF)
        for r in ingame_rows:
            if r.get("korean"):
                ingame.encode_record(rom, int(r["offset"], 16), r["korean"], static)
        rom[POOL8_ROM:POOL8_ROM + 2 + len(pool)] = struct.pack("<H", len(pool)) + bytes(pool)
        g8 = glyph8_table(gs)
        rom[GLYPH8_ROM:GLYPH8_ROM + len(g8)] = g8
        log("in-game font: %d static syllables, %d dynamic slots" % (len(static), len(pool)))
    ltab = label_table(label_rows, gs)
    rom[LABEL_TABLE_ROM:LABEL_TABLE_ROM + len(ltab)] = ltab
    bg2.apply(rom, load_ingame(bg2_csv), log)
    team_tiles = grid.encode(rom, load_ingame(teams_csv))
    rom[RESERVED_ROM:RESERVED_ROM + 64] = reserved_bitmap(original, L.extract(original), label_rows, team_tiles)
    mark_labels(rom, label_rows)
    korean_kanji16(rom)
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
    ingame_csv = os.path.join(ROOT, "translations", "ingame.csv")
    teams_csv = os.path.join(ROOT, "translations", "teams.csv")
    bg2_csv = os.path.join(ROOT, "translations", "bg2.csv")
    if "--csv" in sys.argv:
        csv_path = sys.argv[sys.argv.index("--csv") + 1]
    original = open(args[0], "rb").read()
    rom, _ = build(original, csv_path, labels_csv, ingame_csv, teams_csv, bg2_csv)
    open(args[1], "wb").write(rom)
    print("wrote", args[1], len(rom), "bytes")


if __name__ == "__main__":
    main()
