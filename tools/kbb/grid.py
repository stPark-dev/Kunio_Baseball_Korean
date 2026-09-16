"""Practice-match team grid (`$91:C48B`): 13 records of 12 words
[name_x, y, level_x, y+1, 4 top tile words, 4 bottom tile words], i.e. two 16x16 glyphs
per team name (熱血, 花園, ...). The names are kun readings, so one glyph cannot stand
for one syllable; instead each Korean name is drawn with the 8px font into two dedicated
16x16 glyph slots (SLOT_GLYPHS: glyphs nothing else needs) and the record words are repointed.
The slots must stay out of the label tile pool (see build.reserved_bitmap)."""
import struct

from tools.kbb import font, font8
from tools.kbb.kanji16 import KANJI16, tile_to_index

TABLE = 0x08C48B
RECORD = 24
NAME_PX = 32
# glyph indices no translated screen needs: ち け ・ 勝(x2) 負 決 準 ! 練 習 品 賞 気(dup) 死 攻 後
# 見 作 and the 16px digit pairs 01..89. (0x07/0x47/0x4F are アイテム, 0x41-0x44 野次気合,
# 交代/使用 are the time-out menu; 熱血 and 全米 keep their own glyphs.)
SLOT_GLYPHS = [0x52, 0x5A, 0x49, 0x51, 0x59, 0x78, 0x79, 0x7A, 0x7B, 0x6D, 0x75, 0x76, 0x6E,
               0x68, 0x64, 0x65, 0x5D, 0x27, 0x3F, 0x57, 0x5F, 0x67, 0x6F, 0x77]


def glyph_tiles(ch):
    """(top-left, top-right, bottom-left, bottom-right) tile numbers of a 16x16 glyph (char or index)."""
    k = ch if isinstance(ch, int) else KANJI16.index(ch)
    tl = 0x100 + (k // 8) * 0x20 + (k % 8) * 2
    return tl, tl + 1, tl + 0x10, tl + 0x11


def slot_tiles():
    return {t for ch in SLOT_GLYPHS for t in glyph_tiles(ch)}


def records(rom):
    out, off = [], TABLE
    while True:
        name_x, y, level_x, y1 = struct.unpack_from("<4H", rom, off)
        if y1 != y + 1 or level_x - name_x != 4:
            return out
        words = struct.unpack_from("<8H", rom, off + 8)
        idx = [tile_to_index(w & 0x3FF) for w in words[0:4:2]]
        out.append({"offset": off, "name_x": name_x, "y": y,
                    "japanese": "".join(KANJI16[i] if i is not None else "?" for i in idx)})
        off += RECORD


def name_tiles(text, bdf=None):
    """8 tiles for a name up to 4 syllables: text 8px tall, centred in a 32x16 cell.
    Order: top row (glyph A left/right, glyph B left/right), then the bottom row."""
    px = [[0] * NAME_PX for _ in range(8)]
    x0 = (NAME_PX - 8 * len(text)) // 2
    for i, ch in enumerate(text):
        cell = font8.render8(ch, bdf) if ch != " " else None
        if cell is None:
            continue
        for y in range(8):
            px[y][x0 + i * 8:x0 + i * 8 + 8] = cell[y]
    blank = [0] * 8
    tiles = []
    for half in (0, 1):
        for col in range(4):
            rows = [r[col * 8:col * 8 + 8] for r in px]
            tiles.append(font.encode_tile([blank] * 4 + rows[:4] if half == 0 else rows[4:] + [blank] * 4))
    return tiles


def encode(rom, rows, bdf=None):
    """Draw each translated name into its slots and repoint the record; returns the tiles used."""
    used = set()
    todo = [r for r in rows if r.get("korean")]
    if len(todo) * 2 > len(SLOT_GLYPHS):
        raise ValueError("not enough glyph slots for %d team names" % len(todo))
    for i, r in enumerate(todo):
        a, b = glyph_tiles(SLOT_GLYPHS[2 * i]), glyph_tiles(SLOT_GLYPHS[2 * i + 1])
        order = [a[0], a[1], b[0], b[1], a[2], a[3], b[2], b[3]]
        for t, data in zip(order, name_tiles(r["korean"], bdf)):
            off = font.FONT_OFFSET + t * font.TILE_BYTES
            rom[off:off + font.TILE_BYTES] = data
        struct.pack_into("<8H", rom, int(r["offset"], 16) + 8, *order)
        used.update(order)
    return used
