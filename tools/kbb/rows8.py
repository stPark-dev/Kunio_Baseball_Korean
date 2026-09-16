"""8x8 rows queued straight from ROM to VRAM (`JSL $80F0FD` with X = row words in ROM):
player-info labels and values in bank $90. The queue hook in asm/text.s looks each (bank,
address) up in a table and draws the Korean string instead, so this module only extracts
the rows and builds that table."""
import re
import struct

from tools.kbb import table

RECORD_REGIONS = [(0x082E52, 0x0837E0)]   # [n][n words][m][m mark words]...
# (pointer table, size table, teams): per team two row pointers (marks row, kana row) and one byte count
# every 4 bytes; the manager names under the team pictures of the inning-change scoreboard.
PAIR_TABLES = [(0x016713, 0x016947, 13)]
MARK_TILES = {0x00, 0x02, 0xEB, 0xFB, 0x01, 0x11}
SITE_RE = re.compile(rb"(?:\xa9(..)\xa2(..)\xa0(..)|\xa2(..)\xa0(..)\xa9(..))\x22\xfd\xf0\x80", re.S)


def decode(words):
    out = []
    for w in words:
        t = w & 0xFF
        out.append("_" if t in (0, 2) else (table.TABLE.get(t) or "<%02X>" % t))
    return "".join(out)


def is_marks(words):
    return all((w & 0xFF) in MARK_TILES for w in words)


def extract(rom, banks=(0x10,)):
    """Rows as dicts: id, bank, addr, n, japanese. Mark rows get japanese '(marks)'."""
    rows, seen = [], set()

    def add(bank, addr, words):
        if (bank, addr) in seen or not words:
            return
        seen.add((bank, addr))
        jp = "(marks)" if is_marks(words) else decode(words)
        rows.append({"id": "q_%02X%04X" % (bank, addr), "bank": "%02X" % bank, "addr": "%04X" % addr,
                     "n": len(words), "japanese": jp})

    for m in SITE_RE.finditer(rom):
        g = m.groups()
        vals = [struct.unpack("<H", x)[0] for x in (g[:3] if g[0] is not None else g[3:])]
        nb, src = (vals[0], vals[1]) if g[0] is not None else (vals[2], vals[0])
        bank = m.start() // 0x8000
        if bank not in banks or src < 0x8000 or nb == 0 or nb % 2 or nb > 64:
            continue
        off = bank * 0x8000 + src - 0x8000
        words = struct.unpack_from("<%dH" % (nb // 2), rom, off)
        if any(0x100 <= (w & 0x3FF) < 0x300 for w in words):
            continue                                    # 16x16 rows are handled as glyphs
        add(bank, src, words)
    for start, end in RECORD_REGIONS:
        off = start
        while off < end:
            n = struct.unpack_from("<H", rom, off)[0]
            words = struct.unpack_from("<%dH" % n, rom, off + 2) if 1 <= n <= 32 else ()
            if words and all(0x2000 <= w < 0x2400 for w in words):
                add(off // 0x8000, 0x8000 + off % 0x8000 + 2, words)
                off += 2 + 2 * n
            else:
                off += 2
    for ptrs, sizes, teams in PAIR_TABLES:
        bank = ptrs // 0x8000
        for t in range(teams):
            n = struct.unpack_from("<H", rom, sizes + 4 * t)[0] // 2
            for k in range(2):
                src = struct.unpack_from("<H", rom, ptrs + 4 * t + 2 * k)[0]
                add(bank, src, struct.unpack_from("<%dH" % n, rom, bank * 0x8000 + src - 0x8000))
    return rows


def build_table(rows, gs, base_addr):
    """[u16 count][entries: u8 bank, u16 addr, u16 string][strings]; base_addr = table's bank address."""
    todo = sorted((r for r in rows if r.get("korean")), key=lambda r: (int(r["bank"], 16), int(r["addr"], 16)))
    head = 2 + 5 * len(todo)
    strings, pos, out = [], base_addr + head, bytearray(struct.pack("<H", len(todo)))
    for r in todo:
        s = gs.encode(r["korean"].strip()) if r["korean"].strip() else b"\x00"
        out += struct.pack("<BHH", int(r["bank"], 16), int(r["addr"], 16), pos)
        strings.append(s)
        pos += len(s)
    for s in strings:
        out += s
    return bytes(out)
