"""Glyph bitmaps for the Korean text renderer, taken from the Galmuri11 BDF font.

A glyph cell is 16 rows high. Each row is one 16-bit value, bit 15 = leftmost pixel.
The advance width comes from the BDF DWIDTH (Hangul 12px, Latin 4-9px).
"""
import os
import re

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
BDF_PATH = os.path.join(FONT_DIR, "Galmuri11.bdf")
CELL_H = 16
BASELINE = 14          # BDF FONT_ASCENT: rows 0..13 above the baseline, 14..15 below
GLYPH_BYTES = 32       # 16 rows x u16
MISSING = "?"

_cache = {}


def load_bdf(path=BDF_PATH):
    """Return {codepoint: (dwidth, bbw, bbh, bbx, bby, [row bits...])}."""
    if path in _cache:
        return _cache[path]
    glyphs = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        enc = dw = bbx = None
        rows = None
        for line in f:
            if line.startswith("ENCODING "):
                enc = int(line.split()[1])
            elif line.startswith("DWIDTH "):
                dw = int(line.split()[1])
            elif line.startswith("BBX "):
                bbx = tuple(int(v) for v in line.split()[1:5])
            elif line.startswith("BITMAP"):
                rows = []
            elif line.startswith("ENDCHAR"):
                if enc is not None and enc >= 0:
                    glyphs[enc] = (dw, bbx[0], bbx[1], bbx[2], bbx[3], rows)
                enc = dw = bbx = rows = None
            elif rows is not None:
                rows.append(int(line.strip(), 16) << (16 - 4 * len(line.strip())))  # left-align to 16 bits
    _cache[path] = glyphs
    return glyphs


def render(ch, bdf=None):
    """(width, [16 row values]) for one character; None if the font lacks it."""
    bdf = bdf if bdf is not None else load_bdf()
    g = bdf.get(ord(ch))
    if g is None:
        return None
    dw, bbw, bbh, bx, by, rows = g
    cell = [0] * CELL_H
    top = BASELINE - (by + bbh)
    for i, bits in enumerate(rows):
        y = top + i
        if 0 <= y < CELL_H:
            v = (bits >> bx) if bx >= 0 else (bits << -bx)
            cell[y] |= v & 0xFFFF
    return dw, cell


def pack(cell):
    """16 row values -> 32 bytes, each row little-endian u16."""
    out = bytearray()
    for v in cell:
        out += bytes((v & 0xFF, v >> 8))
    return bytes(out)


def unpack(data):
    return [data[i] | (data[i + 1] << 8) for i in range(0, GLYPH_BYTES, 2)]


def ascii_art(cell, width=16):
    return "\n".join("".join("#" if v & (0x8000 >> x) else "." for x in range(width)) for v in cell)
