import struct

from tools.kbb import build


def test_jml_encoding():
    assert build.jml(0xB18004) == bytes([0x5C, 0x04, 0x80, 0xB1])


def test_apply_patches_checks_original_bytes():
    rom = bytearray(b"\x00" * 16)
    build.apply_patches(rom, [(4, b"\x00\x00", b"\x12\x34")])
    assert rom[4:6] == b"\x12\x34"
    try:
        build.apply_patches(rom, [(4, b"\x00\x00", b"\x56\x78")])
    except build.BuildError:
        pass
    else:
        raise AssertionError("mismatching original bytes must be rejected")


def test_fix_checksum_is_consistent():
    rom = bytearray(range(256)) * (0x8000 // 256)
    build.fix_checksum(rom)
    comp, chk = struct.unpack_from("<HH", rom, build.HEADER_COMPLEMENT)
    assert comp ^ chk == 0xFFFF
    assert build.checksum(rom) == chk


def test_patch_table_addresses_use_table_map():
    p = build.patches({"story": 0x9A22, "surname": 0x8018, "name_extra2": 0x87D5, "item": 0x8A27, "school": 0x99A2})
    # with the original addresses the data patches are no-ops apart from the bank byte
    changed = [off for off, old, new in p if old != new]
    assert 0x0869FA in changed and 0x086A05 not in changed


def test_label_table_and_marking():
    from tools.kbb import encode
    rows = [{"id": "a", "bank": "11", "top": "8003", "bottom": "800B", "n": "4", "korean": "가 나"}]
    gs = encode.GlyphSet(["가 나"])
    data = build.label_table(rows, gs)
    assert data[:2] == struct.pack("<H", 0xC002)
    assert data[2:] == gs.encode("가 나")
    rom = bytearray(0x90000)
    build.mark_labels(rom, rows)
    top = 0x11 * 0x8000 + 3
    assert struct.unpack_from("<H", rom, top)[0] == 0xC000
    assert struct.unpack_from("<H", rom, top + 8)[0] == 0xD000
    assert rom[top + 2:top + 8] == b"\x00" * 6


def test_ingame_font_block_keeps_digits_and_places_static_syllables():
    from tools.kbb import font8
    font = bytes(range(256)) * 16
    block, pool = font8.build_block(font, {"가": font8.FREE[0]})
    assert block[0x03 * 16:0x04 * 16] == font[0x03 * 16:0x04 * 16]       # digit slot untouched
    assert block[font8.FREE[0] * 16:(font8.FREE[0] + 1) * 16] == font8.tile8("가")
    assert font8.FREE[0] not in pool and 0x03 not in pool


def test_encode_record_writes_words_in_place():
    from tools.kbb import ingame
    rom = bytearray(64)
    struct.pack_into("<HH", rom, 0, 0x16, 1)
    ingame.encode_record(rom, 0, "가 1", {"가": 0x09})
    words = struct.unpack_from("<11H", rom, 4)
    assert words[:3] == (0x2009, 0x2002, 0x2013)
    assert words[3:] == (0x2002,) * 8


def test_kanji16_glyphs_are_replaced_with_centered_hangul():
    from tools.kbb import font, glyphs, kanji16
    rom = bytearray(font.FONT_OFFSET + font.FONT_SIZE)
    build.korean_kanji16(rom)
    n = kanji16.KANJI16.index("熱")
    rows = font.glyph16(rom, n)
    dw, cell = glyphs.render("열")
    shift = (16 - dw) // 2
    expect = [[3 if (v >> shift) & (0x8000 >> x) else 0 for x in range(16)] for v in cell]
    assert rows == expect
    assert any(3 in r for r in rows)
    untouched = kanji16.KANJI16.index("率")
    assert font.glyph16(rom, untouched) == [[0] * 16] * 16


def test_grid_records_and_encode():
    from tools.kbb import font, grid
    rom = bytearray(font.FONT_OFFSET + font.FONT_SIZE)
    a, b = grid.glyph_tiles("花"), grid.glyph_tiles("園")
    struct.pack_into("<12H", rom, grid.TABLE, 14, 8, 18, 9, a[0], a[1], b[0], b[1], a[2], a[3], b[2], b[3])
    recs = grid.records(rom)
    assert len(recs) == 1 and recs[0]["japanese"] == "花園" and recs[0]["name_x"] == 14
    used = grid.encode(rom, [{"offset": "%06X" % grid.TABLE, "korean": "하나조노"}])
    s0, s1 = grid.glyph_tiles(grid.SLOT_GLYPHS[0]), grid.glyph_tiles(grid.SLOT_GLYPHS[1])
    words = struct.unpack_from("<8H", rom, grid.TABLE + 8)
    assert words == (s0[0], s0[1], s1[0], s1[1], s0[2], s0[3], s1[2], s1[3])
    assert used == set(words) and used <= grid.slot_tiles()
    top = font.tile(rom, s0[0])
    assert top[:4] == [[0] * 8] * 4 and any(3 in r for r in top[4:])   # text sits in the middle rows
    assert any(3 in r for r in font.tile(rom, s0[2])[:4])


def test_bg2_tile_codec_and_styles():
    from tools.kbb import bg2
    rows = [[(x + y) % 16 for x in range(8)] for y in range(8)]
    assert bg2.decode_tile(bg2.encode_tile(rows), 0) == rows
    tiles = bg2.glyph_tiles("열")
    assert len(tiles) == 4
    colours = {v for t in tiles for r in bg2.decode_tile(t, 0) for v in r}
    assert colours == {0, bg2.FILL, bg2.SHADOW}
    tiles = bg2.banner_tiles("볼")
    assert len(tiles) == 16 and not any(tiles[0]) and any(tiles[3])          # centred: cols 3-4
    assert bg2.OUTLINE in {v for r in bg2.decode_tile(tiles[3], 0) for v in r}
    shared = {t for t in bg2.banner_tiles("볼") if any(t)}
    assert shared <= {t for t in bg2.banner_tiles("플레이 볼") if any(t)}   # word-aligned tiles are reused
    assert len(bg2.overlay_tiles("타율")) == 10


def test_bg2_apply_repoints_rows_into_freed_tiles():
    import struct as st
    from tools.kbb import bg2
    rom = bytearray(bg2.TILESETS["A"] + 0x2000)
    for base in bg2.TILESETS.values():
        rom[base:base + 0x2000] = bytes(range(256)) * 32
    top, banner = 0x100, 0x200
    st.pack_into("<8H", rom, top, 0x3C20, 0x3C21, 0x3C02, 0x3C03, 8, 8, 8, 8)
    st.pack_into("<8H", rom, top + 16, 0x3C30, 0x3C31, 0x3C12, 0x3C13, 8, 8, 0x3CC6, 8)
    words = [0x2008, 0x3C88, 0x3C89, 0x3C8A, 0x3C8B, 0x2008, 0x2008, 0x2008] * 2
    st.pack_into("<16H", rom, banner, *words)
    rows = [{"kind": "glyph", "tileset": "", "target": "60,61,70,71", "korean": "열"},
            {"kind": "overlay", "tileset": "", "target": "%X" % top, "korean": "타율"},
            {"kind": "banner", "tileset": "A", "target": "%X" % banner, "korean": "볼"}]
    pools = bg2.apply(rom, rows, log=lambda *a: None)
    freed = {0x20, 0x21, 0x02, 0x03, 0x30, 0x31, 0x12, 0x13, 0x88, 0x89, 0x8A, 0x8B}
    new = st.unpack_from("<16H", rom, banner)
    used = {w & 0x3FF for w in new if w != bg2.BLANK_WORD}
    assert used and used <= freed and all(w >> 10 == 0x3C00 >> 10 for w in new if w != bg2.BLANK_WORD)
    ov = st.unpack_from("<8H", rom, top)
    assert ov[0] & 0xFC00 == 0x3C00 and ov[2] == 0x0008 and ov[5:] == (8, 8, 8)     # 2 syllables, digits kept
    assert st.unpack_from("<H", rom, top + 16 + 12)[0] == 0x3CC6
    a, b = bg2.TILESETS["A"], bg2.TILESETS["B"]
    t = ov[0] & 0x3FF
    mirrored = bg2.with_background(rom[a + t * 32:a + t * 32 + 32], 2)
    assert rom[b + t * 32:b + t * 32 + 32] == mirrored                              # overlay mirrored into set B on black
    assert rom[a + 0x60 * 32:a + 0x60 * 32 + 32] == bg2.glyph_tiles("열")[0]
    assert rom[b + 0x60 * 32:b + 0x60 * 32 + 32] == bg2.with_background(bg2.glyph_tiles("열")[0], 2)
    assert 0 not in {v for r in bg2.decode_tile(rom, b + 0x60 * 32) for v in r}
    assert pools["A"].free and pools["B"].free
