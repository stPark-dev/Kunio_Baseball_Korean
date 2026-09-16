"""Korean title logo for the title screen.

The logo is one compressed sheet (`$9B:B823` -> `$7F:A000`) whose tiles `0x200`-`0x2FF` are
placed by the BG2 tilemap (`$93:9260` -> `$7F:8800`). Three text blocks sit in it:

    line 1  rows  7-10, cols  9-23   tiles 0xA0.. (palette 7, white outline, cyan->blue fill)
    line 2  rows 11-15, cols  3-28   tiles 0x00.. and 0x50.. (palette 2 red / 6 green)
    sub     rows 17-18, cols  7-25   tiles 0xE0.. and 0x5A.. (palette 7)

Both the tiles and those tilemap rows are replaced at run time (see `kbb_sheet2`), so the
drawing here only has to produce the same tile numbers in the same cells.
"""
import os
import struct

from tools.kbb import glyphs

ART = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "assets", "title_logo.png")
# the drawing's own colours: background/outline white, black, blue, green, red, then two greys
# that the antialiased edges fall into and that we fold into the black outline
ART_REF = ((224, 224, 224), (20, 20, 20), (64, 96, 224), (128, 176, 32), (192, 32, 16),
           (128, 128, 128), (176, 176, 176))
WHITE, BLACK, BLUE, GREEN, RED = 0, 1, 2, 3, 4
# source boxes of the three blocks, measured on the drawing
ART_BOXES = dict(line1=(110, 0, 395, 78), line2=(4, 83, 487, 165), sub=(96, 173, 390, 200))
ART_ERASE = ((360, 0, 492, 26),)             # the cap and ball that overlap the first line
ART_WORDS = ((0, 109, 2), (109, 372, 6), (372, 483, 2))    # line 2: x start, x end, palette
# how each class becomes a palette index, per palette
ART_INK = {2: {BLACK: 3, RED: 9, BLUE: 9, GREEN: 9},
           6: {BLACK: 1, GREEN: 10, BLUE: 10, RED: 10},
           7: {BLACK: 3, BLUE: 11, GREEN: 11, RED: 11}}


def art_classes():
    """(class per pixel, background mask) of the drawing; needs Pillow and numpy."""
    from PIL import Image, ImageFilter
    import numpy as np
    im = Image.open(ART).convert("RGB").filter(ImageFilter.MedianFilter(3))
    a = np.array(im).astype(int)
    ref = np.array(ART_REF)
    cls = ((a[:, :, None, :] - ref[None, None, :, :]) ** 2).sum(axis=3).argmin(axis=2)
    cls[cls > RED] = BLACK                       # antialiased edges join the outline
    for x0, y0, x1, y1 in ART_ERASE:
        cls[y0:y1, x0:x1] = WHITE
    return cls, cls == WHITE                     # the white paper is the transparent background


def art_block(cls, bg, box, size, ink):
    """Palette values for one block.

    Each class is resampled on its own and then applied in priority order, so the one pixel
    outlines survive the reduction instead of being outvoted by the fill they surround."""
    import numpy as np
    from PIL import Image
    x0, y0, x1, y1 = box
    w, h = size
    sub, subbg = cls[y0:y1, x0:x1], bg[y0:y1, x0:x1]
    cover = {}
    for k in ink:
        m = ((sub == k) & ~subbg).astype("uint8") * 255
        cover[k] = np.array(Image.fromarray(m).resize((w, h), Image.BOX)).astype(float) / 255
    out = np.zeros((h, w), int)
    for k, floor in ((BLACK, 0.30), (BLUE, 0.25), (GREEN, 0.25), (RED, 0.25)):
        if k not in cover:
            continue
        take = (out == 0) & (cover[k] >= floor)
        out[take] = ink[k]
    return out.tolist()

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
LINE1 = dict(name="line1", cols=15, rows=4, col=9, row=7, base=0xA0, second=None, pal=7)
LINE2 = dict(name="line2", cols=26, rows=5, col=3, row=11, base=0x00, second=0x50, pal=2,
             words=ART_WORDS)
SUB = dict(name="sub", cols=19, rows=2, col=7, row=17, base=0xE0, second=0x5A, pal=7,
           text="야구로 승부다! 쿠니오군", style=(3, 1, 1))
BLOCKS = (LINE1, LINE2, SUB)
LETTER_W = 24


# Tile 0x47 of this sheet is the blank tile that every other cell of the title screen points at,
# so drawing on it stripes the whole screen: those cells borrow a tile nothing else uses.
SHARED_TILES = {0x47: 0x9A}


def line_tile(block, r, c):
    """Buffer tile number of cell (r, c) of a block; wide blocks wrap into a second tile range."""
    if c < 16 or block["second"] is None:
        t = block["base"] + r * 16 + c
    else:
        t = block["second"] + r * 16 + (c - 16)
    return SHARED_TILES.get(t, t)


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


def canvas(block, art=None):
    """(palette per canvas cell column, canvas of 4bpp values) traced from the drawing."""
    width, height = block["cols"] * 8, block["rows"] * 8
    if block.get("text"):                # too small to trace: set in the pixel font instead
        vals = styled(proportional_ink(block["text"], width, height), block["pal"],
                      block.get("style"))
        return [block["pal"]] * block["cols"], vals
    cls, bg = art if art else art_classes()
    x0, y0, x1, y1 = ART_BOXES[block["name"]]
    out = [[0] * width for _ in range(height)]
    pal_col = [block["pal"]] * block["cols"]
    for sx0, sx1, pal in block.get("words") or ((0, x1 - x0, block["pal"]),):
        cell0 = round(sx0 * width / (x1 - x0) / 8)
        cell1 = round(sx1 * width / (x1 - x0) / 8)
        vals = art_block(cls, bg, (x0 + sx0, y0, x0 + sx1, y1), ((cell1 - cell0) * 8, height),
                         block.get("ink") or ART_INK[pal])
        for c in range(cell0, min(cell1, block["cols"])):
            pal_col[c] = pal
        for y, row in enumerate(vals):
            for x, v in enumerate(row):
                if v and cell0 * 8 + x < width:
                    out[y][cell0 * 8 + x] = v
    return pal_col, out


def tiles_and_map(block, art=None):
    """({tile number: 32 bytes}, {tilemap word offset: word}) for one block."""
    pal_col, cv = canvas(block, art)
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


# The game over screen writes げーむ おーばー with a 24x24 font of its own (three tile rows of the
# sheet at $9B:8000, placed by the tilemap at $92:9C99). Korean goes into free tiles of that sheet.
# Four screens share this sheet, so the nine tiles of each syllable go into different free runs.
GAMEOVER = dict(text="게임 오버", row=20, col=9, blocks=(0x130, 0x0B0, 0x112, 0x152),
                ink=1, back=2, blank=0x2D00, attr=0x2C00, wipe=(7, 26))


def block_tiles(ch, back, ink):
    """Nine 8x8 tiles of one 24x24 syllable drawn in `ink` on `back`."""
    g = bolder(scaled_glyph(ch, 24, 24))
    px = [[ink if g[y][x] else back for x in range(24)] for y in range(24)]
    return [encode_tile([row[c * 8:c * 8 + 8] for row in px[r * 8:r * 8 + 8]])
            for r in range(3) for c in range(3)]


# The same screen greets the player with おつかれさま above the picture: nine tiles by two rows.
THANKS = dict(text="수고하셨어요", fill=13, shade=14,
              tiles=(0x10D, 0x10E, 0x10F, 0x12D, 0x12E, 0x12F, 0x14D, 0x14E, 0x14F,
                     0x11D, 0x11E, 0x11F, 0x13D, 0x13E, 0x13F, 0x15D, 0x15E, 0x15F))


def thanks():
    """{sheet byte offset: 32 bytes} for the greeting, drawn at the font's own 12px pitch."""
    t = THANKS
    ink = proportional_ink(t["text"], 9 * 8, 16)
    px = [[t["fill"] if v else 0 for v in row] for row in ink]
    for y in range(15, -1, -1):
        for x in range(9 * 8 - 1, -1, -1):
            if px[y][x] == t["fill"]:
                for dy, dx in ((1, 0), (0, 1), (1, 1)):
                    if y + dy < 16 and x + dx < 9 * 8 and px[y + dy][x + dx] == 0:
                        px[y + dy][x + dx] = t["shade"]
    out = {}
    for i, tile in enumerate(t["tiles"]):
        r, c = i // 9, i % 9
        out[tile * 32] = encode_tile([row[c * 8:c * 8 + 8] for row in px[r * 8:r * 8 + 8]])
    return out


def gameover():
    """({sheet byte offset: 32 bytes}, {tilemap byte offset: word}) for the game over line."""
    g = GAMEOVER
    tiles, tmap = {}, {}
    col, block = g["col"], iter(g["blocks"])
    for ch in g["text"]:
        if ch == " ":
            col += 2
            continue
        t = next(block)
        for i, data in enumerate(block_tiles(ch, g["back"], g["ink"])):
            tiles[(t + i) * 32] = data
        for r in range(3):
            for c in range(3):
                tmap[((g["row"] + r) * 32 + col + c) * 2] = g["attr"] | (t + r * 3 + c)
        col += 3
    for r in range(3):                       # wipe the cells the Japanese line used
        for c in range(*g["wipe"]):
            tmap.setdefault(((g["row"] + r) * 32 + c) * 2, g["blank"])
    return tiles, tmap


def build():
    """(tile number -> 32 bytes, tilemap word offset -> word) for the whole logo."""
    tiles, tmap = {}, {}
    art = art_classes()
    for block in BLOCKS:
        t, m = tiles_and_map(block, art)
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
