"""Korean headline for the newspaper scene (script scene `0x7F`).

The page is two layers. The paper comes from uncompressed tiles at `$96:C7E5` with the tilemap
`$92:94FC` -> `$7F:8000`; over it sits a headline band whose art is the compressed sheet
`$AB:DBE6` -> `$7F:9800` and whose tilemap is `$92:90ED` -> `$7F:9000`. The band is rows 10-15,
and the Japanese ホームラン fills it nearly cell for cell, every cell with a tile of its own.
Two colours only: the box is 4, the brush strokes are 0.

Korean says it in two syllables, so the band's rows become two blocks of 6x6 tiles and those
tiles are drawn. The tilemap cannot be patched the way the other screens' are: it reaches VRAM
through the plain `$7F` DMA (script command 06), which runs *before* the command 1C upload that
the blob table hooks. So the command 16 record that unpacks it is pointed at a stream of our own
instead (`lz.encode`), and the Korean map is what lands in the buffer in the first place.
"""
import struct

from tools.kbb import glyphs, lz, sprtext

MAP_STREAM, MAP_DICT = 0x9290ED, 0x92AB05
MAP_RECORD = 0x0018E2                        # the scene's "16 dest(3) source(3) dictionary(3)"
MAP_DEST = 0x7F9000
SHEET_STREAM, SHEET_DICT = 0xABDBE6, 0xABECCE
SHEET_DEST = 0x9800                          # $7F address the headline sheet unpacks to
TEXT = "홈런"
ROW, COL, CELLS = 10, 10, 6                  # band rows 10-15; two 6x6 blocks from column 10
FIRST_TILE = 0x02                            # tiles 0x02-0x49 belong to the Japanese headline alone
BLANK, ATTR = 0x2C01, 0x2C00                 # the box's own background word; the letters' palette
BACK, INK = 4, 0
SIZE = 40                                    # letter size inside the 48px block: 4px of air all round


def block_tile(i, r, c):
    """Sheet tile of cell (r, c) of the i-th syllable."""
    return FIRST_TILE + (i * CELLS + r) * CELLS + c


def tiles():
    """{sheet byte offset: 32 bytes} for the Korean headline."""
    out = {}
    side = CELLS * 8
    pad = (side - SIZE) // 2
    for i, ch in enumerate(TEXT):
        px = [[BACK] * side for _ in range(side)]
        for y, row in enumerate(glyphs.stretch(ch, SIZE, SIZE)):
            for x, v in enumerate(row):
                if v:
                    px[pad + y][pad + x] = INK
        for r in range(CELLS):
            for c in range(CELLS):
                out[block_tile(i, r, c) * 32] = sprtext.encode4(
                    [row[c * 8:c * 8 + 8] for row in px[r * 8:r * 8 + 8]])
    return out


def tilemap():
    """{buffer byte offset: word} for the band's rows: blank, with the two blocks in the middle."""
    out = {((ROW + r) * 32 + c) * 2: BLANK for r in range(CELLS) for c in range(32)}
    for i in range(len(TEXT)):
        for r in range(CELLS):
            for c in range(CELLS):
                col = COL + i * CELLS + c
                out[((ROW + r) * 32 + col) * 2] = ATTR | block_tile(i, r, c)
    return out


def record(source, dictionary):
    """The scene's command 16 record with `source` and `dictionary` swapped in."""
    return (bytes((lz.CMD,)) + struct.pack("<I", MAP_DEST)[:3]
            + struct.pack("<I", source)[:3] + struct.pack("<I", dictionary)[:3])


def sheet_run():
    """(stream, dictionary, buffer offset, length, $7F address) of the headline's tiles."""
    off = FIRST_TILE * 32
    return SHEET_STREAM, SHEET_DICT, off, CELLS * CELLS * len(TEXT) * 32, SHEET_DEST + off


def map_stream(rom):
    """The Korean headline tilemap as a stream the game's decompressor can read."""
    buf = bytearray(lz.decompress(rom, lz.snes_to_rom(MAP_STREAM), lz.snes_to_rom(MAP_DICT)))
    for off, word in tilemap().items():
        struct.pack_into("<H", buf, off, word)
    return lz.encode(bytes(buf))
