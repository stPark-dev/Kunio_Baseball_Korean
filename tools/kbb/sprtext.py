"""Story-scene location titles (熱血高校, 虹が丘2丁目 ...): 16x16 glyphs inside the scene's
compressed 4bpp sheet, decompressed by the game to $7F:B000 and uploaded by $81:8586.
The asm hook `kbb_sheet` scans that buffer before the DMA and replaces every 8x8 tile that
matches a signature with its Korean tile, so the table is keyed by tile bitmaps and works in
any scene that reuses the same glyph art. translations/sprtext.csv holds one row per glyph:
kanji, korean, the four quadrant tiles (tl, tr, bl, br) as hex, and the box background colour
(`bg`, 15 in most scenes, 13 in the hospital)."""
import struct

from tools.kbb import font8, glyphs

INK = 1                # palette: colour 1 is the white of the titles
BG = 15               # the title tiles are boxes of colour 15 (black) with colour-1 strokes
TILE = 32


def decode4(data, off=0):
    rows = []
    for y in range(8):
        rows.append([sum((((data[off + (p // 2) * 16 + y * 2 + (p % 2)] >> (7 - x)) & 1) << p)
                         for p in range(4)) for x in range(8)])
    return rows


def encode4(rows):
    out = bytearray(TILE)
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            for p in range(4):
                if (v >> p) & 1:
                    out[(p // 2) * 16 + y * 2 + (p % 2)] |= 0x80 >> x
    return bytes(out)


def korean_cell(text):
    """16x16 ink matrix: one syllable centred (Galmuri11) or two 8px syllables stretched."""
    px = [[0] * 16 for _ in range(16)]
    if len(text) == 2:
        for i, c in enumerate(text):
            cell = font8.render8(c) or [[0] * 8] * 8
            for y in range(8):
                for x in range(8):
                    if cell[y][x]:
                        px[2 * y][8 * i + x] = px[2 * y + 1][8 * i + x] = 1
    elif text.strip():
        dw, cell = glyphs.render(text[0]) or (12, [0] * 16)
        shift = (16 - dw) // 2
        for y in range(16):
            for x in range(16):
                if x >= shift and (cell[y] >> (15 - (x - shift))) & 1:
                    px[y][x] = 1
    return px


def quadrants(px, bg=BG):
    """(tl, tr, bl, br) 4bpp tiles of a 16x16 ink matrix drawn in INK on colour `bg`."""
    out = []
    for oy, ox in ((0, 0), (0, 8), (8, 0), (8, 8)):
        out.append(encode4([[INK if px[oy + y][ox + x] else bg for x in range(8)] for y in range(8)]))
    return out


def first_word_bitmap(table):
    """8 KB bitmap indexed by a tile's first word: set when some signature starts with that word.
    The asm scan skips every tile whose bit is clear, so only real candidates are compared."""
    count = struct.unpack_from("<H", table, 0)[0]
    bits = bytearray(0x2000)
    for i in range(count):
        w = struct.unpack_from("<H", table, 2 + 64 * i)[0]
        bits[w >> 3] |= 1 << (w & 7)
    return bytes(bits)


def group_cells(texts):
    """One 16x16 ink matrix per cell for a title whose cells are adjacent on screen.

    The whole string is laid out proportionally (Galmuri11) across cells * 16 pixels and then
    cut back into cells, so a reading that needs more syllables than cells still looks even.
    Only titles whose cells really do sit side by side may use this (`group` in the CSV);
    most titles are drawn with gaps between the cells and stay one syllable per cell."""
    text = "".join(texts)
    width = 16 * len(texts)
    glyph = [glyphs.render(c) or (12, [0] * 16) for c in text]
    pen = max(0, (width - sum(dw for dw, _ in glyph)) // 2)
    px = [[0] * width for _ in range(16)]
    for dw, cell in glyph:
        for y in range(16):
            for x in range(dw):
                if pen + x < width and (cell[y] >> (15 - x)) & 1:
                    px[y][pen + x] = 1
        pen += dw
    return [[row[i * 16:(i + 1) * 16] for row in px] for i in range(len(texts))]


def build_table(rows):
    """[u16 count][entries: 32-byte signature, 32-byte replacement]; blank quadrants are skipped."""
    entries = []
    grouped = {}
    for r in rows:
        if r.get("group"):
            grouped.setdefault(r["group"], []).append(r)
    cells = {}
    for members in grouped.values():
        for r, px in zip(members, group_cells([m.get("korean", "") for m in members])):
            cells[id(r)] = px
    for r in rows:
        if not r.get("korean"):
            continue
        reps = quadrants(cells.get(id(r)) or korean_cell(r["korean"]), int(r.get("bg") or BG))
        for key, rep in zip(("tl", "tr", "bl", "br"), reps):
            sig = bytes.fromhex(r[key])
            if len(sig) != TILE or not any(sig):
                continue
            entries.append(sig + rep)
    return struct.pack("<H", len(entries)) + b"".join(entries)


def extract(buf, tiles):
    """Hex quadrants of a glyph whose (tl, tr, bl, br) tile numbers are given, from a sheet."""
    return {k: buf[t * TILE:(t + 1) * TILE].hex() for k, t in zip(("tl", "tr", "bl", "br"), tiles)}
