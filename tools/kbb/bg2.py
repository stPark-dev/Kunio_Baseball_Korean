"""Match-screen graphic text on BG2 (4bpp tiles at VRAM $A000).

Two 256-tile sets exist in ROM: TILESETS["A"] for the pitch/bat view and TILESETS["B"] for
the field view; both keep the scoreboard elements (digits, inning label, team abbreviations,
OUT counter) at the same tile numbers. Text is drawn three ways:

- glyph:   a 16x16 kanji redrawn in place (team abbreviation, 表, 裏), in both sets.
- half:    an 8x16 syllable (the inning counter's 回); `target` lists one or more top,bottom pairs.
- blank:   tiles wiped clean, for the parts of a replaced image that nothing draws any more.
- copy:    a tile duplicated into a second slot ("src>dst"), for images the game stores twice.
- overlay: a stats-overlay label row pair (`$85:F9D2`...: 8 words per row, label in the first
           4-5 columns, digits after). Redrawn with the 8px font stretched to 8x16 like the
           digits, one column per syllable, and the row words repointed. Same tiles in both sets.
- banner:  a 2x8-word image (`$8E:FC72`... records, `$8E:FE14`... headerless). Redrawn with
           Galmuri11, one word per column-aligned span so words such as 볼/게임 share tiles.

New tiles come from the tiles the replaced images used to reference, per set."""
import struct

from tools.kbb import font8, glyphs

TILESETS = {"A": 0x0E6000, "B": 0x0C8000}
BACKGROUND = {"A": 0, "B": 2}                  # scoreboard tiles: transparent in A, black in B
BLANK_TILE = 0x08
BLANK_WORD = 0x2008
OVERLAY_COLS = 5
BANNER_COLS = 8
ADVANCE = 12
FILL, SHADOW, OUTLINE = 1, 15, 2               # palette 7: 1 white, 15 dark, 2 black
GRADIENT = {2: 14, 3: 14, 4: 13, 5: 13, 6: 12, 7: 11, 8: 1, 9: 11, 10: 12,
            11: 13, 12: 14, 13: 14, 14: 14}    # banner fill colour by row (as the original)


class Bg2Error(Exception):
    pass


def decode_tile(data, off):
    rows = []
    for y in range(8):
        b0, b1, b2, b3 = data[off + y * 2], data[off + y * 2 + 1], data[off + 16 + y * 2], data[off + 17 + y * 2]
        rows.append([((b0 >> (7 - x)) & 1) | (((b1 >> (7 - x)) & 1) << 1)
                     | (((b2 >> (7 - x)) & 1) << 2) | (((b3 >> (7 - x)) & 1) << 3) for x in range(8)])
    return rows


def encode_tile(rows):
    out = bytearray(32)
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            for p in range(4):
                if (v >> p) & 1:
                    out[(p // 2) * 16 + y * 2 + (p % 2)] |= 0x80 >> x
    return bytes(out)


def with_background(data, bg):
    """Tile bytes with colour 0 replaced by `bg` (set B draws the scoreboard on black)."""
    if bg == 0:
        return data
    return encode_tile([[v or bg for v in row] for row in decode_tile(data, 0)])


def ink16(ch):
    """(advance, 16x16 0/1 matrix) of a Galmuri11 glyph; '?' box when missing."""
    g = glyphs.render(ch)
    if g is None:
        g = glyphs.render("?")
    dw, cell = g
    return dw, [[(v >> (15 - x)) & 1 for x in range(16)] for v in cell]


def shade(canvas, x, y, colour):
    if 0 <= y < len(canvas) and 0 <= x < len(canvas[0]) and canvas[y][x] == 0:
        canvas[y][x] = colour


def kanji_style(ink):
    """White fill with a dark drop shadow (the style of the scoreboard kanji and digits)."""
    h, w = len(ink), len(ink[0])
    out = [[FILL if ink[y][x] else 0 for x in range(w)] for y in range(h)]
    for y in range(h):
        for x in range(w):
            if ink[y][x]:
                shade(out, x + 1, y + 1, SHADOW)
    return out


def banner_style(ink):
    """Black outline with the original's row gradient inside."""
    h, w = len(ink), len(ink[0])
    out = [[GRADIENT.get(y, 14) if ink[y][x] else 0 for x in range(w)] for y in range(h)]
    for y in range(h):
        for x in range(w):
            if ink[y][x]:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        shade(out, x + dx, y + dy, OUTLINE)
    return out


def slice_tiles(canvas):
    """Colour canvas (16 rows x 8*cols) -> tiles in row-major order (top row first)."""
    cols = len(canvas[0]) // 8
    return [encode_tile([r[c * 8:c * 8 + 8] for r in canvas[half * 8:half * 8 + 8]])
            for half in (0, 1) for c in range(cols)]


def glyph_tiles(ch):
    """4 tiles (tl, tr, bl, br) of one 16x16 kanji-style Hangul syllable, centred."""
    dw, ink = ink16(ch)
    shift = (16 - dw) // 2
    ink = [[row[x - shift] if x >= shift else 0 for x in range(16)] for row in ink]
    return slice_tiles(kanji_style(ink))


def word_canvas(text):
    """Banner word: 12px advance, outline clipped to the word's own column span."""
    n = len(text)
    cols = (ADVANCE * n + 7) // 8
    ink = [[0] * (cols * 8) for _ in range(16)]
    for i, ch in enumerate(text):
        _, g = ink16(ch)
        for y in range(16):
            for x in range(16):
                if g[y][x] and i * ADVANCE + x < cols * 8:
                    ink[y][i * ADVANCE + x] = 1
    out = banner_style(ink)
    limit = ADVANCE * n
    return cols, [row[:limit] + [0] * (cols * 8 - limit) for row in out]


def banner_tiles(text):
    """Tiles for a whole banner (16 words: top row then bottom row), blank tiles as None."""
    words = [word_canvas(w) for w in text.split()]
    cols = sum(c for c, _ in words)
    if cols > BANNER_COLS:
        raise Bg2Error("banner too wide (%d columns): %s" % (cols, text))
    pad = (BANNER_COLS - cols) // 2
    canvas = [[0] * (BANNER_COLS * 8) for _ in range(16)]
    x = pad * 8
    for c, px in words:
        for y in range(16):
            canvas[y][x:x + c * 8] = px[y]
        x += c * 8
    return slice_tiles(canvas)


def half_tiles(ch):
    """(top, bottom) tiles of one 8x16 syllable: the inning counter's 回 is half width."""
    ink = [[0] * 8 for _ in range(16)]
    cell = font8.render8(ch)
    if cell is not None:
        for y in range(8):
            for x in range(8):
                if cell[y][x]:
                    ink[y * 2][x] = ink[y * 2 + 1][x] = 1
    return slice_tiles(kanji_style(ink))


def overlay_tiles(text):
    """Stats label: one 8x16 column per syllable (Galmuri7 stretched 2x vertically)."""
    if len(text) > OVERLAY_COLS:
        raise Bg2Error("overlay label too long: %s" % text)
    ink = [[0] * (OVERLAY_COLS * 8) for _ in range(16)]
    for i, ch in enumerate(text):
        cell = font8.render8(ch)
        if cell is None:
            continue
        for y in range(8):
            for x in range(8):
                if cell[y][x]:
                    ink[y * 2][i * 8 + x] = ink[y * 2 + 1][i * 8 + x] = 1
    return slice_tiles(kanji_style(ink))


class Pool:
    """Tile allocator for one tileset: identical tiles share a slot, blank tiles map to 0x08."""

    def __init__(self, rom, base, free):
        self.rom, self.base = rom, base
        self.free = sorted(free)
        self.cache = {}

    def get(self, data):
        if not any(data):
            return BLANK_TILE
        if data in self.cache:
            return self.cache[data]
        if not self.free:
            raise Bg2Error("BG2 tileset at %06X is out of free tiles" % self.base)
        t = self.free.pop(0)
        self.rom[self.base + t * 32:self.base + t * 32 + 32] = data
        self.cache[data] = t
        return t


def image_tiles(rom, off, count):
    return {w & 0x3FF for w in struct.unpack_from("<%dH" % count, rom, off) if w not in (BLANK_WORD, 0x0008)}


def apply(rom, rows, log=print):
    """Draw every translated row of translations/bg2.csv into `rom` (bytearray, in place)."""
    todo = [r for r in rows if r.get("korean")]
    for r in todo:
        if r["kind"] == "copy":                     # second copy of a tile (see inning_kai_dup)
            for pair in r["target"].split(","):
                src, dst = (int(t, 16) for t in pair.split(">"))
                for base in TILESETS.values():
                    rom[base + dst * 32:base + dst * 32 + 32] = rom[base + src * 32:base + src * 32 + 32]
            continue
        if r["kind"] == "blank":                    # leftovers of a replaced image (see inning_tail)
            for t in (int(t, 16) for t in r["target"].split(",")):
                for base in TILESETS.values():
                    rom[base + t * 32:base + t * 32 + 32] = bytes(32)
            continue
        if r["kind"] == "half":                     # 8x16 syllable, drawn into every listed pair
            data = half_tiles(r["korean"])
            for pair in r["target"].split("|"):
                for t, d in zip((int(t, 16) for t in pair.split(",")), data):
                    for key, base in TILESETS.items():
                        rom[base + t * 32:base + t * 32 + 32] = with_background(d, BACKGROUND[key])
            continue
        if r["kind"] != "glyph":
            continue
        tiles = [int(t, 16) for t in r["target"].split(",")]
        for key, base in TILESETS.items():
            for t, data in zip(tiles, glyph_tiles(r["korean"])):
                rom[base + t * 32:base + t * 32 + 32] = with_background(data, BACKGROUND[key])
    overlay = [r for r in todo if r["kind"] == "overlay"]
    free = set()
    for r in overlay:
        top = int(r["target"], 16)
        free |= image_tiles(rom, top, 4) | image_tiles(rom, top + 16, 4)
    pools = {k: Pool(rom, base, set()) for k, base in TILESETS.items()}
    pool_a = Pool(rom, TILESETS["A"], free)
    for r in overlay:
        top = int(r["target"], 16)
        tiles = overlay_tiles(r["korean"])
        pal = struct.unpack_from("<H", rom, top)[0] & 0xFC00
        for half, row_off in ((0, top), (1, top + 16)):
            for c in range(OVERLAY_COLS):
                data = tiles[half * OVERLAY_COLS + c]
                t = pool_a.get(data)
                if t != BLANK_TILE:
                    b = TILESETS["B"]
                    rom[b + t * 32:b + t * 32 + 32] = with_background(data, BACKGROUND["B"])
                struct.pack_into("<H", rom, row_off + c * 2, 0x0008 if t == BLANK_TILE else pal | t)
    spare = set(pool_a.free)
    for key in TILESETS:
        banners = [r for r in todo if r["kind"] == "banner" and r["tileset"] == key]
        tiles = set(spare)
        for r in banners:
            tiles |= image_tiles(rom, int(r["target"], 16), 16)
        pool = Pool(rom, TILESETS[key], tiles)
        for r in banners:
            off = int(r["target"], 16)
            for i, data in enumerate(banner_tiles(r["korean"])):
                t = pool.get(data)
                struct.pack_into("<H", rom, off + i * 2, BLANK_WORD if t == BLANK_TILE else 0x3C00 | t)
        pools[key] = pool
        log("BG2 set %s: %d banners, %d free tiles left" % (key, len(banners), len(pool.free)))
    return pools
