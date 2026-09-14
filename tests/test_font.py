from tools.kbb.font import decode_tile, encode_tile, glyph16, FONT_OFFSET, tile


def test_decode_encode_roundtrip():
    raw = bytes(range(16))
    assert encode_tile(decode_tile(raw, 0)) == raw


def test_decode_tile_bitplanes():
    raw = bytes([0x80, 0x00] + [0x00, 0x01] + [0xFF, 0xFF] + [0] * 10)
    rows = decode_tile(raw, 0)
    assert rows[0] == [1, 0, 0, 0, 0, 0, 0, 0]
    assert rows[1] == [0, 0, 0, 0, 0, 0, 0, 2]
    assert rows[2] == [3] * 8


def test_glyph16_uses_sheet_layout():
    rom = bytearray(FONT_OFFSET + 0x3000)
    # glyph 9 -> row 1, col 1 -> top-left tile 0x100 + 0x20 + 2 = 0x122
    for t, v in ((0x122, 0x80), (0x123, 0x01), (0x132, 0x40), (0x133, 0x02)):
        rom[FONT_OFFSET + t * 16] = v          # first row, low plane
    g = glyph16(bytes(rom), 9)
    assert g[0][0] == 1 and g[0][15] == 1 and g[8][1] == 1 and g[8][14] == 1
    assert tile(bytes(rom), 0x122)[0][0] == 1
