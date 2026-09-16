"""Korean title logo for the title screen.

The logo is one compressed sheet (`$9B:B823` -> `$7F:A000`) whose tiles `0x200`-`0x2FF` are
placed by the BG2 tilemap (`$93:9260` -> `$7F:8800`). Three text blocks sit in it:

    line 1  rows  7-10, cols  9-23   tiles 0xA0.. (palette 7, white outline, cyan->blue fill)
    line 2  rows 11-15, cols  3-28   tiles 0x00.. and 0x50.. (palette 2 red / 6 green)
    sub     rows 17-18, cols  7-25   tiles 0xE0.. and 0x5A.. (palette 7)

Both the tiles and those tilemap rows are replaced at run time (see `kbb_sheet2`), so the
drawing here only has to produce the same tile numbers in the same cells.
"""
import struct

from tools.kbb import glyphs

BLANK_TILE = 0x247
PAL_ATTR = {2: 0x2800, 6: 0x3800, 7: 0x3C00}
# palette index of the outline and of the top and bottom of the vertical fill gradient
STYLE = {2: (3, 5, 9), 6: (1, 5, 14), 7: (1, 5, 15)}


def scaled_glyph(ch, w, h):
    """16x16 Galmuri11 glyph stretched to w x h as a 0/1 matrix."""
    g = glyphs.render(ch)
    if g is None:
        return [[0] * w for _ in range(h)]
    _, cell = g
    return [[(cell[y * 16 // h] >> (15 - (x * 16 // w))) & 1 for x in range(w)] for y in range(h)]


def bolder(ink):
    """One pixel of weight down and to the right; scaled font strokes are too thin for a logo."""
    h, w = len(ink), len(ink[0])
    return [[1 if any(0 <= y - dy < h and 0 <= x - dx < w and ink[y - dy][x - dx]
                      for dy in (0, 1) for dx in (0, 1)) else 0 for x in range(w)] for y in range(h)]


def word_ink(text, w, h):
    ink = [[0] * (w * len(text)) for _ in range(h)]
    for i, ch in enumerate(text):
        g = bolder(scaled_glyph(ch, w, h))
        for y in range(h):
            ink[y][i * w:(i + 1) * w] = g[y]
    return ink


def styled(ink, palette, style=None):
    """Ink matrix -> 4bpp values: gradient fill with a one pixel outline around it."""
    outline, lo, hi = style or STYLE[palette]
    h, w = len(ink), len(ink[0])
    rows = [r for r in range(h) if any(ink[r])]
    top, bot = (rows[0], rows[-1]) if rows else (0, h - 1)
    span = max(1, bot - top)
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        v = lo + round((hi - lo) * (y - top) / span)
        for x in range(w):
            if ink[y][x]:
                out[y][x] = min(max(v, lo), hi)
    for y in range(h):
        for x in range(w):
            if out[y][x]:
                continue
            if any(0 <= y + dy < h and 0 <= x + dx < w and ink[y + dy][x + dx]
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                out[y][x] = outline
    return out


def place(canvas, block, x0):
    for y, row in enumerate(block):
        canvas[y][x0:x0 + len(row)] = row


# Each block: the screen cells it covers and the words in it (x offset in the canvas, palette).
LINE1 = dict(name="line1", cols=15, rows=4, col=9, row=7, base=0xA0, second=None,
             words=[("다운타운", 8, 7)], height=30)
LINE2 = dict(name="line2", cols=26, rows=5, col=3, row=11, base=0x00, second=0x50,
             words=[("열혈", 8, 2), ("야구", 72, 6), ("이야기", 136, 2)], height=38)
SUB = dict(name="sub", cols=19, rows=2, col=7, row=17, base=0xE0, second=0x5A,
           words=[("야구로 승부다! 쿠니오군", None, 7)], height=16, style=(3, 1, 1))
BLOCKS = (LINE1, LINE2, SUB)
LETTER_W = 24


def line_tile(block, r, c):
    """Buffer tile number of cell (r, c) of a block; wide blocks wrap into a second tile range."""
    if c < 16 or block["second"] is None:
        return block["base"] + r * 16 + c
    return block["second"] + r * 16 + (c - 16)


def proportional_ink(text, width, height):
    """Galmuri11 at its own size, centred: used for the small subtitle line."""
    runs = [glyphs.render(ch) for ch in text]
    pen = (width - sum(r[0] if r else 6 for r in runs)) // 2
    ink = [[0] * width for _ in range(height)]
    for r in runs:
        if r is None:
            pen += 6
            continue
        dw, cell = r
        for y in range(min(16, height)):
            for x in range(dw):
                if (cell[y] >> (15 - x)) & 1 and 0 <= pen + x < width:
                    ink[y][pen + x] = 1
        pen += dw
    return ink


def canvas(block):
    """(palette per canvas cell column, canvas of 4bpp values) for one block."""
    width, height = block["cols"] * 8, block["rows"] * 8
    out = [[0] * width for _ in range(height)]
    pal_col = [block["words"][0][2]] * block["cols"]
    top = (height - block["height"]) // 2
    for text, x0, pal in block["words"]:
        if x0 is None:
            ink = proportional_ink(text, width, block["height"])
            block_x = 0
        else:
            ink = word_ink(text, LETTER_W, block["height"])
            block_x = x0
        vals = styled(ink, pal, block.get("style"))
        for y, row in enumerate(vals):
            for x, v in enumerate(row):
                if v and block_x + x < width:
                    out[top + y][block_x + x] = v
        for c in range((block_x) // 8, min(block["cols"], (block_x + len(ink[0]) + 7) // 8)):
            pal_col[c] = pal
    return pal_col, out


def tiles_and_map(block):
    """({tile number: 32 bytes}, {tilemap word offset: word}) for one block."""
    pal_col, cv = canvas(block)
    tiles, tmap = {}, {}
    for r in range(block["rows"]):
        for c in range(block["cols"]):
            t = line_tile(block, r, c)
            tiles[t] = encode_tile([row[c * 8:c * 8 + 8] for row in cv[r * 8:r * 8 + 8]])
            off = ((block["row"] + r) * 32 + block["col"] + c) * 2
            tmap[off] = PAL_ATTR[pal_col[c]] | (0x200 + t)
    return tiles, tmap


# The two red words of line 2 are drawn again as sprites over BG2, from uncompressed tiles in
# ROM. The 60 slots hold the same art as the BG tiles below, column by column right to left.
SPRITE_ROM = 0x155860
SPRITE_ORDER = ([r * 16 + 5 for r in (4, 3, 2, 1, 0)]
                + [r * 16 + c for r in (4, 3, 2, 1, 0) for c in (4, 3, 2, 1, 0)]
                + [0x50 + r * 16 + 9 for r in (4, 3, 2, 1, 0)]
                + [0x50 + r * 16 + c for r in (4, 3, 2, 1, 0) for c in (8, 7, 6, 5, 4)])


def sprite_patches(tiles):
    """[(rom offset, 32 bytes)] so the sprite copy shows the same Korean word as the BG tiles."""
    return [(SPRITE_ROM + i * 32, tiles[t]) for i, t in enumerate(SPRITE_ORDER) if t in tiles]


def build():
    """(tile number -> 32 bytes, tilemap word offset -> word) for the whole logo."""
    tiles, tmap = {}, {}
    for block in BLOCKS:
        t, m = tiles_and_map(block)
        tiles.update(t)
        tmap.update(m)
    return tiles, tmap


def encode_tile(values):
    """8x8 palette values -> 32 bytes, 4bpp planar."""
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            v = values[y][x]
            for p in range(4):
                if (v >> p) & 1:
                    out[(p // 2) * 16 + y * 2 + (p % 2)] |= 0x80 >> x
    return bytes(out)
