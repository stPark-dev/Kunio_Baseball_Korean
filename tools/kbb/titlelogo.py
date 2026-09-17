"""Korean title logo for the title screen.

The logo is one compressed sheet (`$9B:B823` -> `$7F:A000`) whose tiles `0x200`-`0x2FF` are
placed by the BG2 tilemap (`$93:9260` -> `$7F:8800`). Three text blocks sit in it:

    line 1  rows  7-10, cols  9-23   tiles 0xA0.. (palette 7, white outline, cyan->blue fill)
    line 2  rows 11-15, cols  3-28   tiles 0x00.. and 0x50.. (palette 2 red / 6 green)
    sub     rows 17-18, cols  7-25   tiles 0xE0.. and 0x5A.. (palette 7)

Both the tiles and those tilemap rows are replaced at run time (see `kbb_sheet2`), so the
drawing here only has to produce the same tile numbers in the same cells.

Only the letter shapes come from `assets/title_logo.png`. The colouring is the original logo's
own, measured off the Japanese title screen: every palette holds a vertical gradient and one or
two outline colours, and `styled` puts each word back together that way, so the Korean logo
belongs to the screen it sits on instead of looking like a shrunk drawing.
"""
import os
import struct

from tools.kbb import glyphs, lz

ART = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "assets", "title_logo.png")
ART_ALPHA = 200                              # the drawing is transparent around the letters
# Where each word sits in the drawing, and the cells of its block it fills. The two red words
# keep the cells the sprite copy expects (see SPRITE_ORDER), so their spans cannot move.
ART_WORDS = {
    "line1": (((435, 113, 1462, 375), 0, 15, 7),),
    "line2": (((43, 396, 427, 717), 0, 6, 2),
              ((448, 396, 1435, 717), 6, 20, 6),
              ((1455, 396, 1856, 717), 20, 26, 2)),
}


def art_ink():
    """The drawing's letter bodies as one boolean mask.

    Only the coloured fill is traced. The white halo and the black keyline the drawing puts
    around it are not part of the shape: the logo gets its outline from `styled` instead, in
    the colours the title screen's palettes actually hold."""
    from PIL import Image
    import numpy as np
    a = np.array(Image.open(ART).convert("RGBA")).astype(int)
    r, g, b, alpha = (a[:, :, i] for i in range(4))
    grey = (abs(r - g) < 45) & (abs(g - b) < 45) & (abs(r - b) < 45)
    return (alpha > ART_ALPHA) & ~grey


def word_shape(ink, box, width, height):
    """`box` of the drawing as a width x height boolean shape.

    The drawing is about ten times the size it ends up at, and plain area coverage closes the
    gaps between strokes on the way down, which turns 열혈 into two solid blocks. Taking half a
    destination pixel off the shape first keeps them open."""
    from PIL import Image, ImageFilter
    import numpy as np
    x0, y0, x1, y1 = box
    img = Image.fromarray((ink[y0:y1, x0:x1] * 255).astype("uint8"))
    shrink = round(0.5 * (x1 - x0) / width)
    if shrink:
        img = img.filter(ImageFilter.MinFilter(2 * shrink + 1))
    return np.array(img.resize((width, height), Image.BOX)) >= 128


BLANK_TILE = 0x247
PAL_ATTR = {2: 0x2800, 6: 0x3800, 7: 0x3C00}
# (fill at the top, fill at the bottom, outline rings from the letter outwards), read off the
# original logo: the red words wear white around a black keyline, the other two a single ring.
STYLE = {2: (9, 5, (3, 1)), 6: (14, 5, (1,)), 7: (5, 15, (1,))}


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


def styled(ink, palette, style=None):
    """Ink matrix -> 4bpp values: a vertical gradient inside, outline rings around it."""
    head, foot, rings = style or STYLE[palette]
    h, w = len(ink), len(ink[0])
    rows = [r for r in range(h) if any(ink[r])]
    top, bot = (rows[0], rows[-1]) if rows else (0, h - 1)
    span = max(1, bot - top)
    lo, hi = min(head, foot), max(head, foot)
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        v = min(max(head + round((foot - head) * (y - top) / span), lo), hi)
        for x in range(w):
            if ink[y][x]:
                out[y][x] = v
    grown = [[1 if v else 0 for v in row] for row in ink]
    for colour in rings:
        ring = [[not grown[y][x] and any(grown[y + dy][x + dx]
                                         for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                                         if 0 <= y + dy < h and 0 <= x + dx < w)
                 for x in range(w)] for y in range(h)]
        for y in range(h):
            for x in range(w):
                if ring[y][x]:
                    out[y][x] = colour
                    grown[y][x] = 1
    return out


# Each block: the screen cells it covers and the words in it (x offset in the canvas, palette).
LINE1 = dict(name="line1", cols=15, rows=4, col=9, row=7, base=0xA0, second=None, pal=7)
LINE2 = dict(name="line2", cols=26, rows=5, col=3, row=11, base=0x00, second=0x50, pal=2)
SUB = dict(name="sub", cols=19, rows=2, col=7, row=17, base=0xE0, second=0x5A, pal=7,
           text="야구로 승부다! 쿠니오군", style=(1, 1, (3,)))
BLOCKS = (LINE1, LINE2, SUB)


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


def canvas(block, ink=None):
    """(palette per cell column, canvas of 4bpp values) traced from the drawing."""
    width, height = block["cols"] * 8, block["rows"] * 8
    if block.get("text"):                # too small to trace: set in the pixel font instead
        return ([block["pal"]] * block["cols"],
                styled(proportional_ink(block["text"], width, height), block["pal"],
                       block.get("style")))
    ink = art_ink() if ink is None else ink
    out = [[0] * width for _ in range(height)]
    pal_col = [block["pal"]] * block["cols"]
    for box, cell0, cell1, pal in ART_WORDS[block["name"]]:
        pad = len(STYLE[pal][2])         # the rings are drawn outside the ink, so leave room
        cols = (cell1 - cell0) * 8
        cell = [[0] * cols for _ in range(height)]
        for y, row in enumerate(word_shape(ink, box, cols - 2 * pad, height - 2 * pad)):
            for x, v in enumerate(row):
                if v:
                    cell[pad + y][pad + x] = 1
        vals = styled(cell, pal)
        for c in range(cell0, cell1):
            pal_col[c] = pal
        for y in range(height):
            out[y][cell0 * 8:cell1 * 8] = vals[y]
    return pal_col, out


def tiles_and_map(block, ink=None):
    """({tile number: 32 bytes}, {tilemap word offset: word}) for one block."""
    pal_col, cv = canvas(block, ink)
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


# Every tilemap that places tiles of the sheet at $9B:8000. Rows 20-22 are where the ending cards
# and the game over line sit, i.e. the cells the patches below rewrite, so a tile used only there
# is free for us: the four screens differ in nothing else.
SHEET_MAPS = (0x928533, 0x9289B4, 0x928792, 0x928C49, 0x928953, 0x928CEE, 0x928E09,
              0x929C99, 0x929DDA)
SHEET_MAP_DICT = 0x92AB05
SHEET_TILES = 0x200
TEXT_ROWS = range(20, 23)


def free_tiles(rom):
    """Tiles of the shared sheet that no screen points at outside the rows we rewrite."""
    used = set()
    for src in SHEET_MAPS:
        m = lz.decompress(rom, lz.snes_to_rom(src), lz.snes_to_rom(SHEET_MAP_DICT))
        for r in (r for r in range(32) if r not in TEXT_ROWS):
            for c in range(32):
                i = (r * 32 + c) * 2
                if i + 1 < len(m):
                    used.add((m[i] | (m[i + 1] << 8)) & 0x3FF)
    return set(range(SHEET_TILES)) - used


# The game over screen writes げーむ おーばー with a 24x24 font of its own (three tile rows of the
# sheet at $9B:8000, placed by the tilemap at $92:9C99). Korean goes into free tiles of that sheet,
# nine per syllable, taken in order from `blocks`. The Japanese line's own tiles are no use: its お
# is the very nine the ending cards draw お with. Up to v0.6.5 these were four runs of nine picked
# by eye, and three of the runs cut through the victory banners and the sunset ending card.
GAMEOVER = dict(text="게임 오버", row=20, col=9, ink=1, back=2, blank=0x2D00, attr=0x2C00,
                wipe=(7, 26),
                blocks=(0x079, 0x07A, 0x07B, 0x07C, 0x0BF, 0x0CE, 0x0CF, 0x0D9, 0x0EA,
                        0x0F0, 0x0F1, 0x0FA, 0x0FD, 0x101, 0x102, 0x106, 0x109, 0x10A,
                        0x10B, 0x10C, 0x112, 0x11A, 0x11B, 0x11C, 0x122, 0x12B, 0x12C,
                        0x133, 0x134, 0x135, 0x13B, 0x13C, 0x147, 0x14A, 0x157, 0x158))


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


# The victory screen hangs two banners down the school wall, both in this same sheet and both two
# tiles wide: 祝優勝!! in the left one (tile column 0, rows 7-14) and おめでとう in the right
# (column 2, rows 8-15). Its tilemap already points at those tiles, so only the art changes.
# The two girls stand in front of the wall and hide everything below screen line 110, so the
# Korean stops there: the left banner keeps the `!!` of its last two tile rows, which no one ever
# sees, and the right one has its bottom two rows wiped instead of holding a う nobody reads.
# 祝 is painted apart from 優勝 on the original banner, the way a Korean banner writes 축 apart
# from 우승, so the colours are kept one per syllable.
BANNERS = (dict(col=0, row=7, rows=6, back=1, x=1, w=13, h=13, top=3, pitch=15,
                ink=(("축", 7), ("우", 8), ("승", 8))),
           dict(col=2, row=8, rows=8, back=1, x=1, w=13, h=13, top=2, pitch=15,
                ink=(("축", 9), ("하", 9), ("해", 9))))


def banner_glyph(ch, w, h):
    """Galmuri11's glyph stretched to fill a w x h box.

    `scaled_glyph` keeps the font's 16px cell, in which a Hangul syllable is 11px wide, so it
    would leave a banner letter filling two thirds of the cloth. A painted banner runs edge to
    edge, so the glyph's own ink box is what gets stretched."""
    _, cell = glyphs.render(ch)
    rows = [[(v >> (15 - x)) & 1 for x in range(16)] for v in cell]
    ys = [y for y, r in enumerate(rows) if any(r)]
    xs = [x for r in rows for x, v in enumerate(r) if v]
    box = [r[min(xs):max(xs) + 1] for r in rows[ys[0]:ys[-1] + 1]]
    return [[box[y * len(box) // h][x * len(box[0]) // w] for x in range(w)] for y in range(h)]


def victory():
    """{sheet byte offset: 32 bytes} for the two banners of the victory screen."""
    out = {}
    for b in BANNERS:
        px = [[b["back"]] * 16 for _ in range(b["rows"] * 8)]
        for i, (ch, colour) in enumerate(b["ink"]):
            for y, row in enumerate(banner_glyph(ch, b["w"], b["h"])):
                for x, v in enumerate(row):
                    if v:
                        px[b["top"] + i * b["pitch"] + y][b["x"] + x] = colour
        for r in range(b["rows"]):
            for c in range(2):
                out[((b["row"] + r) * 16 + b["col"] + c) * 32] = encode_tile(
                    [row[c * 8:c * 8 + 8] for row in px[r * 8:r * 8 + 8]])
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
        nine = [next(block) for _ in range(9)]
        for t, data in zip(nine, block_tiles(ch, g["back"], g["ink"])):
            tiles[t * 32] = data
        for r in range(3):
            for c in range(3):
                tmap[((g["row"] + r) * 32 + col + c) * 2] = g["attr"] | nine[r * 3 + c]
        col += 3
    for r in range(3):                       # wipe the cells the Japanese line used
        for c in range(*g["wipe"]):
            tmap.setdefault(((g["row"] + r) * 32 + c) * 2, g["blank"])
    return tiles, tmap


def build():
    """(tile number -> 32 bytes, tilemap word offset -> word) for the whole logo."""
    tiles, tmap = {}, {}
    ink = art_ink()
    for block in BLOCKS:
        t, m = tiles_and_map(block, ink)
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
