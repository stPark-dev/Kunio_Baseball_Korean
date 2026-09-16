"""8x8 Korean glyphs (Galmuri7) for the in-game screens, as 2bpp SNES tiles.

The match screens have no spare VRAM for the 16px cache, so in-game text uses the
8x8 font area itself: a fixed font block per scene where kana/kanji slots hold
Korean syllables, plus a dynamic pool of slots refilled at run time.
"""
import os

from tools.kbb import glyphs
from tools.kbb.font import encode_tile

BDF7 = os.path.join(glyphs.FONT_DIR, "Galmuri7.bdf")
INK = 3


def render8(ch, bdf=None):
    """8 rows of 8 pixel values (0/INK) for one character; None if missing."""
    bdf = bdf if bdf is not None else glyphs.load_bdf(BDF7)
    g = bdf.get(ord(ch))
    if g is None:
        return None
    dw, bbw, bbh, bx, by, rows = g
    cell = [[0] * 8 for _ in range(8)]
    top = 8 - bbh - by                      # bottom aligned, 1px margin for 7px glyphs
    for i, bits in enumerate(rows):
        y = top + i
        if 0 <= y < 8:
            for x in range(8):
                px = x - bx
                if 0 <= px < 16 and bits & (0x8000 >> px):
                    cell[y][x] = INK
    return cell


def tile8(ch, bdf=None):
    """16 bytes (2bpp tile) or None."""
    cell = render8(ch, bdf)
    return encode_tile(cell) if cell is not None else None


# 8x8 font slots that stay as in the original font (digits, Latin, marks, HUD kanji, graphics)
KEEP = set(range(0x03, 0x100, 0x10)) | set(range(0x04, 0x100, 0x10)) | set(range(0x05, 0x100, 0x10)) | {
    0x00, 0x01, 0x02, 0x06, 0x08, 0x11, 0x12, 0x18, 0x21, 0x22, 0x27, 0x28, 0x31, 0x32, 0x38, 0x48, 0x58,
    0x26, 0x36, 0x37,                       # 体 of the HUD stamina bars (0x27 is its other copy)
    0x72, 0x77, 0x82, 0x87, 0x92, 0x97, 0xA3, 0xB3, 0xB7, 0xC2, 0xC3, 0xC7, 0xD2, 0xD3, 0xD7, 0xE2, 0xE3,
    0xE7, 0xEB, 0xEF, 0xFB, 0xFF,
    0x0C, 0x1C, 0x2C, 0x3C, 0x4C, 0x5C,     # 2-colour kanji used by the stats overlay
}
FREE = [t for t in range(0x100) if t not in KEEP]


def build_block(font, static, bdf=None):
    """In-game 4 KB font block.

    font: original 4 KB 8x8 font; static: {char: tile index} for baked syllables.
    Returns (block bytes, dynamic pool tile list)."""
    block = bytearray(font)
    used = set(static.values())
    for ch, t in static.items():
        data = tile8(ch, bdf) or tile8("?", bdf)
        block[t * 16:(t + 1) * 16] = data
    pool = [t for t in FREE if t not in used]
    for t in pool:                              # dynamic slots start blank, not as stale kana
        block[t * 16:(t + 1) * 16] = bytes(16)
    return bytes(block), pool
