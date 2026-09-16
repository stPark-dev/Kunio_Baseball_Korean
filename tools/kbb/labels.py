"""Pre-drawn tile-row text ("labels"): menus, team names, screen headers.

Every such row is written by JSL $91B390 with X=column, Y=row, A=address of n
tile words (in the caller's data bank) and n pushed on the stack. Two calls with
Y and Y+1 make a 16px-high label: the top row carries dakuten marks or the upper
halves of 16x16 glyphs. This module finds the call sites, recovers the operands
statically and decodes the words with the font tables.

Usage: python -m tools.kbb.labels ROM [labels.csv]
"""
import csv
import os
import re
import struct
import sys

from tools.kbb import table as T
from tools.kbb.kanji16 import DIGIT_PAIRS, KANJI16, tile_to_index

ROW_WRITER = b"\x22\x90\xb3\x91"      # JSL $91B390
SCAN_BACK = 40

# (list address, entry count): lists of [x][y][n] + 2n words records drawn by $11:8BE7 / $11:96xx
RECORD_LISTS = [(0x088C9F, 33), (0x08996F, 11)]
# (table address, entry count, n): tables of row addresses, consecutive entries = top/bottom rows
ROW_TABLES = [(0x080385, 16, 12), (0x08413A, 26, 17)]
# (list address, entry count): lists of [n u16][top n words][bottom n words] records drawn by $11:C8DD
COUNTED_LISTS = [(0x08C986, 21)]
# practice-match team grid ($91:C48B): 13 records of [name_x, y, level_x, y+1, 4 top words, 4 bottom words],
# drawn with the row writer (n = 4); their labels use the 8px font (see build.NARROW_PREFIX)
GRID_RECORDS = (0x08C48B, 13)
# (pointer table, entry count, n): labels copied by the MVN writer $90:CA94; each pointer is a block of
# n top words followed by n bottom words (the stat labels of the next-opponent screen)
MVN_TABLES = [(0x0820D1, 14, 6)]
# (stream, dictionary, buffer offset, n): rows inside compressed tilemaps (bank $7F buffers), identified by
# their first word when the scene uploads the map; bank "7F", top = offset, bottom = offset + 64
MAP_ROWS = [(0x93B7BC, 0x93B8AB, 0x01C8, 12), (0x93B7BC, 0x93B8AB, 0x0388, 16), (0x93B7BC, 0x93B8AB, 0x03B0, 4),
            (0x93B7BC, 0x93B8AB, 0x0486, 4), (0x93B7BC, 0x93B8AB, 0x049C, 6), (0x93B7BC, 0x93B8AB, 0x0586, 6),
            (0x93B7BC, 0x93B8AB, 0x059C, 4), (0x93B7BC, 0x93B8AB, 0x05AE, 4)]
# (bank, top, bottom, n): 16x16 rows sent through the VRAM queue ($80:F0FD) by the pre-game vertical
# menu and the time-out menu (normal and highlighted variants); the queue hook draws marked rows
QUEUE_ROWS = [(0x02, 0xB28E, 0xB2F4, 8), (0x02, 0xB29E, 0xB304, 8), (0x02, 0xB2AE, 0xB314, 6),
              (0x02, 0xB2BA, 0xB320, 8), (0x02, 0xB2CA, 0xB330, 8), (0x02, 0xB2DA, 0xB340, 4),
              (0x02, 0xB35A, 0xB3C0, 8), (0x02, 0xB36A, 0xB3D0, 8), (0x02, 0xB37A, 0xB3E0, 6),
              (0x02, 0xB386, 0xB3EC, 8), (0x02, 0xB396, 0xB3FC, 8), (0x02, 0xB3A6, 0xB40C, 4),
              (0x02, 0xB8B0, 0xB8F8, 8), (0x02, 0xB8C0, 0xB908, 8), (0x02, 0xB8D0, 0xB918, 8),
              (0x02, 0xB8E0, 0xB928, 4), (0x02, 0xB940, 0xB988, 8), (0x02, 0xB950, 0xB998, 8),
              (0x02, 0xB960, 0xB9A8, 8), (0x02, 0xB970, 0xB9B8, 4)]
# (bank, top, bottom, n): rows whose call sites pass position/width in registers
EXTRA_ROWS = [(0x2B, 0xF6D6, 0xF6EA, 10), (0x2B, 0xF7A2, 0xF7B6, 10), (0x2B, 0xF7CA, 0xF7DE, 10),
              (0x2B, 0xF7F2, 0xF806, 10), (0x2B, 0xF841, 0xF855, 10)]


def glyph_tiles(ch):
    """(top-left, top-right, bottom-left, bottom-right) tile numbers of a 16x16 glyph (char or index)."""
    k = ch if isinstance(ch, int) else KANJI16.index(ch)
    tl = 0x100 + (k // 8) * 0x20 + (k % 8) * 2
    return tl, tl + 1, tl + 0x10, tl + 0x11


def rom_to_snes(off):
    return ((off // 0x8000) << 16) | 0x8000 | (off % 0x8000)


def snes_to_rom(addr):
    return ((addr >> 16) & 0x3F) * 0x8000 + ((addr & 0xFFFF) - 0x8000)


def decode_rows(top, bot):
    """Two rows of tile words -> text."""
    out = []
    i = 0
    n = len(bot)
    while i < n:
        t, tt = bot[i] & 0x3FF, top[i] & 0x3FF
        k = tile_to_index(tt)
        if k is not None and i + 1 < n and (bot[i] & 0x3FF) == tt + 0x10:
            out.append(DIGIT_PAIRS.get(tt, KANJI16[k]))
            i += 2
            continue
        ch = T.TABLE.get(t, "" if t in (0, 2) else "{%03X}" % t)
        if tt == 0x001:
            ch = T.voiced(ch, "゙")
        elif tt == 0x011:
            ch = T.voiced(ch, "゚")
        out.append(ch)
        i += 1
    return "".join(out)


def _operands(code):
    """Recover A (data address), n, X, Y from the bytes before a call site."""
    ops = {}
    for m in re.finditer(rb"\xa9(..)", code):          # LDA #imm16
        ops["a"] = (struct.unpack("<H", m.group(1))[0], m.start())
    for m in re.finditer(rb"\xf4(.)\x00", code):       # PEA n (n < 256)
        ops["n"] = (m.group(1)[0], m.start())
    for m in re.finditer(rb"\xa2(.)\x00", code):
        ops["x"] = (m.group(1)[0], m.start())
    for m in re.finditer(rb"\xa0(.)\x00", code):
        ops["y"] = (m.group(1)[0], m.start())
    for m in re.finditer(rb"\xbd(..)", code):          # LDA table,X
        ops["table"] = (struct.unpack("<H", m.group(1))[0], m.start())
    return ops


def call_sites(rom):
    """Yield dicts describing each $91B390 call whose operands are static."""
    for m in re.finditer(re.escape(ROW_WRITER), rom):
        site = m.start()
        code = rom[site - SCAN_BACK:site]
        ops = _operands(code)
        bank = site // 0x8000
        entry = {"site": site, "bank": bank, "n": ops.get("n", (None,))[0],
                 "x": ops.get("x", (None,))[0], "y": ops.get("y", (None,))[0]}
        if "a" in ops and ("table" not in ops or ops["a"][1] > ops["table"][1]):
            entry["addr"] = ops["a"][0]
        elif "table" in ops:
            entry["table"] = ops["table"][0]
        yield entry


def pair_rows(sites):
    """Group consecutive static calls into (top, bottom) label pairs.

    The bottom row usually follows the top row immediately, with the same bank,
    column and width; its row is Y+1 (LDY) or set with INY (Y unchanged)."""
    pairs = []
    prev = None
    for s in sites:
        if "addr" not in s or s["n"] is None or s["x"] is None:
            prev = None
            continue
        if (prev and prev["y"] is not None and prev["bank"] == s["bank"] and prev["x"] == s["x"]
                and prev["n"] == s["n"] and prev["addr"] != s["addr"]
                and (s["y"] is None or s["y"] in (prev["y"], prev["y"] + 1))):
            pairs.append((prev, s))
            prev = None
        else:
            prev = s
    return pairs


def words(rom, bank, addr, n):
    off = bank * 0x8000 + (addr - 0x8000)
    return struct.unpack_from("<%dH" % n, rom, off)


def map_buffer(rom, row):
    """Decompressed tilemap that holds a bank-7F row (its id names the stream)."""
    from tools.kbb import lz
    src = int(row["id"].split("_")[1], 16)
    dic = next(d for s, d, _, _ in MAP_ROWS if s == src)
    return lz.decompress(rom, lz.snes_to_rom(src), lz.snes_to_rom(dic))


def row_words(rom, row, key, buf=None):
    """Tile words of a row's top or bottom line; bank-7F rows are read from their tilemap buffer."""
    n, addr = int(row["n"]), int(row[key], 16)
    if row["bank"] == "7F":
        buf = buf if buf is not None else map_buffer(rom, row)
        return struct.unpack_from("<%dH" % n, buf, addr)
    return words(rom, int(row["bank"], 16), addr, n)


def extract(rom):
    rows = []
    for top, bot in pair_rows(list(call_sites(rom))):
        text = decode_rows(words(rom, top["bank"], top["addr"], top["n"]),
                           words(rom, bot["bank"], bot["addr"], bot["n"]))
        rows.append({"id": "site_%06X" % top["site"], "bank": "%02X" % top["bank"],
                     "top": "%04X" % top["addr"], "bottom": "%04X" % bot["addr"],
                     "n": top["n"], "x": top["x"], "y": top["y"], "japanese": text, "korean": ""})
    for table_off, count, n in ROW_TABLES:
        bank = table_off // 0x8000
        for k in range(0, count, 2):
            top_addr, bot_addr = struct.unpack_from("<HH", rom, table_off + 2 * k)
            rows.append({"id": "tab_%06X_%02d" % (table_off, k // 2), "bank": "%02X" % bank,
                         "top": "%04X" % top_addr, "bottom": "%04X" % bot_addr, "n": n, "x": 0, "y": 0,
                         "japanese": decode_rows(words(rom, bank, top_addr, n), words(rom, bank, bot_addr, n)),
                         "korean": ""})
    for list_off, count in COUNTED_LISTS:
        bank = list_off // 0x8000
        for k in range(count):
            addr = struct.unpack_from("<H", rom, list_off + 2 * k)[0]
            off = snes_to_rom((bank << 16) | addr)
            n = struct.unpack_from("<H", rom, off)[0]
            top = struct.unpack_from("<%dH" % n, rom, off + 2)
            bot = struct.unpack_from("<%dH" % n, rom, off + 2 + 2 * n)
            rows.append({"id": "cnt_%06X_%02d" % (list_off, k), "bank": "%02X" % bank,
                         "top": "%04X" % (addr + 2), "bottom": "%04X" % (addr + 2 + 2 * n),
                         "n": n, "x": 0, "y": 0, "japanese": decode_rows(top, bot), "korean": ""})
    for bank, top_addr, bot_addr, n in EXTRA_ROWS:
        rows.append({"id": "row_%02X%04X" % (bank, top_addr), "bank": "%02X" % bank,
                     "top": "%04X" % top_addr, "bottom": "%04X" % bot_addr, "n": n, "x": 0, "y": 0,
                     "japanese": decode_rows(words(rom, bank, top_addr, n), words(rom, bank, bot_addr, n)),
                     "korean": ""})
    for list_off, count in RECORD_LISTS:
        bank = list_off // 0x8000
        for k in range(count):
            addr = struct.unpack_from("<H", rom, list_off + 2 * k)[0]
            off = snes_to_rom((bank << 16) | addr)
            x, y, n = rom[off], rom[off + 1], rom[off + 2]
            top = struct.unpack_from("<%dH" % n, rom, off + 3)
            bot = struct.unpack_from("<%dH" % n, rom, off + 3 + 2 * n)
            rows.append({"id": "rec_%06X_%02d" % (list_off, k), "bank": "%02X" % bank,
                         "top": "%04X" % (addr + 3), "bottom": "%04X" % (addr + 3 + 2 * n),
                         "n": n, "x": x, "y": y, "japanese": decode_rows(top, bot), "korean": ""})
    table, count = GRID_RECORDS
    bank = table // 0x8000
    for k in range(count):
        off = table + 24 * k
        x, y = struct.unpack_from("<HH", rom, off)
        top, bot = struct.unpack_from("<4H", rom, off + 8), struct.unpack_from("<4H", rom, off + 16)
        addr = 0x8000 + off % 0x8000
        rows.append({"id": "grid_%02d" % k, "bank": "%02X" % bank, "top": "%04X" % (addr + 8),
                     "bottom": "%04X" % (addr + 16), "n": 4, "x": x, "y": y,
                     "japanese": decode_rows(top, bot), "korean": ""})
    for table_off, count, n in MVN_TABLES:
        bank = table_off // 0x8000
        for k in range(count):
            top_addr = struct.unpack_from("<H", rom, table_off + 2 * k)[0]
            bot_addr = top_addr + 2 * n
            rows.append({"id": "mvn_%06X_%02d" % (table_off, k), "bank": "%02X" % bank,
                         "top": "%04X" % top_addr, "bottom": "%04X" % bot_addr, "n": n, "x": 0, "y": 0,
                         "japanese": decode_rows(words(rom, bank, top_addr, n), words(rom, bank, bot_addr, n)),
                         "korean": ""})
    for bank, top_addr, bot_addr, n in QUEUE_ROWS:
        rows.append({"id": "que_%02X%04X" % (bank, top_addr), "bank": "%02X" % bank,
                     "top": "%04X" % top_addr, "bottom": "%04X" % bot_addr, "n": n, "x": 0, "y": 0,
                     "japanese": decode_rows(words(rom, bank, top_addr, n), words(rom, bank, bot_addr, n)),
                     "korean": ""})
    rows += map_rows(rom)
    return rows


def map_rows(rom):
    from tools.kbb import lz
    rows, bufs = [], {}
    for src, dic, off, n in MAP_ROWS:
        if src not in bufs:
            bufs[src] = lz.decompress(rom, lz.snes_to_rom(src), lz.snes_to_rom(dic))
        top = struct.unpack_from("<%dH" % n, bufs[src], off)
        bot = struct.unpack_from("<%dH" % n, bufs[src], off + 64)
        rows.append({"id": "map_%06X_%04X" % (src, off), "bank": "7F", "top": "%04X" % off,
                     "bottom": "%04X" % (off + 64), "n": n, "x": (off % 64) // 2, "y": off // 64,
                     "japanese": decode_rows(top, bot), "korean": ""})
    return rows


def main():
    rom = open(sys.argv[1], "rb").read()
    rows = extract(rom)
    if len(sys.argv) > 2:
        if os.path.exists(sys.argv[2]):        # keep translations already entered
            with open(sys.argv[2], encoding="utf-8") as f:
                old = {r["id"]: r["korean"] for r in csv.DictReader(f)}
            for r in rows:
                r["korean"] = old.get(r["id"], "")
        with open(sys.argv[2], "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id", "bank", "top", "bottom", "n", "x", "y", "japanese", "korean"])
            w.writeheader()
            w.writerows(rows)
    for r in rows:
        print(r["id"], r["bank"], r["top"], "n=%d" % r["n"], "(%d,%d)" % (r["x"], r["y"]), repr(r["japanese"]))
    static = sum(1 for s in call_sites(rom) if "addr" in s)
    print(len(rows), "labels;", static, "static call sites of", len(list(call_sites(rom))))


if __name__ == "__main__":
    main()
