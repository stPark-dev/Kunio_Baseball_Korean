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
ROW_TABLES = [(0x080385, 16, 12), (0x08413A, 8, 17)]
# (list address, entry count): lists of [n u16][top n words][bottom n words] records drawn by $11:C8DD
COUNTED_LISTS = [(0x08C986, 21)]
# (bank, top, bottom, n): rows whose call sites pass position/width in registers
EXTRA_ROWS = [(0x2B, 0xF6D6, 0xF6EA, 10), (0x2B, 0xF7A2, 0xF7B6, 10), (0x2B, 0xF7CA, 0xF7DE, 10),
              (0x2B, 0xF7F2, 0xF806, 10), (0x2B, 0xF841, 0xF855, 10)]


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
