"""Read the game's 2bpp text font and render reference sheets.

Font block: ROM 0x0B47E5, 0x3000 bytes = 768 tiles (2bpp, 16 bytes each).
  tiles 0x000-0x0FF : 8x8 text font (see table.py)
  tiles 0x100-0x2FF : 128 16x16 glyphs laid out on a 16-tile-wide sheet
                      (char n: top-left tile 0x100 + (n // 8) * 0x20 + (n % 8) * 2,
                       top-right +1, bottom-left +0x10, bottom-right +0x11)
"""
import sys

from PIL import Image, ImageDraw

FONT_OFFSET = 0x0B47E5
FONT_SIZE = 0x3000
TILE_BYTES = 16


def decode_tile(data, off):
    """2bpp SNES tile -> 8 rows of 8 pixel values (0-3)."""
    rows = []
    for y in range(8):
        lo, hi = data[off + y * 2], data[off + y * 2 + 1]
        rows.append([((lo >> (7 - x)) & 1) | (((hi >> (7 - x)) & 1) << 1) for x in range(8)])
    return rows


def encode_tile(rows):
    """Inverse of decode_tile."""
    out = bytearray()
    for row in rows:
        lo = hi = 0
        for x, v in enumerate(row):
            lo |= (v & 1) << (7 - x)
            hi |= ((v >> 1) & 1) << (7 - x)
        out += bytes((lo, hi))
    return bytes(out)


def tile(rom, index):
    return decode_tile(rom, FONT_OFFSET + index * TILE_BYTES)


def glyph16(rom, n):
    """16x16 glyph n (0-127) as 16 rows of 16 pixels."""
    tl = 0x100 + (n // 8) * 0x20 + (n % 8) * 2
    quads = [tile(rom, tl), tile(rom, tl + 1), tile(rom, tl + 0x10), tile(rom, tl + 0x11)]
    return [quads[(y // 8) * 2][y % 8] + quads[(y // 8) * 2 + 1][y % 8] for y in range(16)]


def _blit(px, rows, ox, oy, scale):
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            c = v * 85
            for dy in range(scale):
                for dx in range(scale):
                    px[ox + x * scale + dx, oy + y * scale + dy] = c


def sheet8(rom, scale=6):
    cell = 8 * scale + 14
    im = Image.new("L", (cell * 16 + 40, cell * 16 + 16), 40)
    dr, px = ImageDraw.Draw(im), im.load()
    for i in range(256):
        ox, oy = 40 + (i % 16) * cell, 16 + (i // 16) * cell
        _blit(px, tile(rom, i), ox, oy, scale)
        dr.text((ox + 8, oy + 8 * scale), "%02X" % i, fill=220)
    return im


def sheet16(rom, scale=4):
    cell = 16 * scale + 14
    im = Image.new("L", (cell * 8 + 40, cell * 16 + 16), 40)
    dr, px = ImageDraw.Draw(im), im.load()
    for n in range(128):
        ox, oy = 40 + (n % 8) * cell, 16 + (n // 8) * cell
        _blit(px, glyph16(rom, n), ox, oy, scale)
        dr.text((ox + 8, oy + 16 * scale), "%02X" % n, fill=220)
    return im


if __name__ == "__main__":
    rom = open(sys.argv[1], "rb").read()
    sheet8(rom).save(sys.argv[2])
    sheet16(rom).save(sys.argv[3])
    print("wrote", sys.argv[2], sys.argv[3])
