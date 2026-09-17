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
    sites = build.label_sites(rows)
    assert struct.unpack_from("<H", sites, 0)[0] == 2
    assert struct.unpack_from("<BHH", sites, 2) == (0x11, 0x8003, 0)
    assert struct.unpack_from("<BHH", sites, 7) == (0x11, 0x800B, build.LABEL_ROW_BOTTOM)


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
    untouched = kanji16.KANJI16.index("練")      # a glyph no screen needs, so it is never redrawn
    assert font.glyph16(rom, untouched) == [[0] * 16] * 16


def test_label_kinds_grid_mvn_map(monkeypatch):
    from tools.kbb import labels, lz
    rom = bytearray(0x100000)
    table, _ = labels.GRID_RECORDS
    a, b = labels.glyph_tiles("花"), labels.glyph_tiles("園")
    struct.pack_into("<12H", rom, table, 14, 8, 18, 9, a[0], a[1], b[0], b[1], a[2], a[3], b[2], b[3])
    monkeypatch.setattr(labels, "GRID_RECORDS", (table, 1))
    monkeypatch.setattr(labels, "MVN_TABLES", [(0x0820D0, 1, 3)])
    struct.pack_into("<H", rom, 0x0820D0, 0xA105)
    k = labels.glyph_tiles("打")
    struct.pack_into("<3H", rom, 0x82105, 0x2000 | k[0], 0x2000 | k[1], 0x2002)
    struct.pack_into("<3H", rom, 0x8210B, 0x2000 | k[2], 0x2000 | k[3], 0x2002)
    buf = bytearray(2048)
    n = labels.glyph_tiles("次")
    struct.pack_into("<2H", buf, 0x1C8, 0x2C00 | n[0], 0x2C00 | n[1])
    struct.pack_into("<2H", buf, 0x1C8 + 64, 0x2C00 | n[2], 0x2C00 | n[3])
    monkeypatch.setattr(labels, "MAP_ROWS", [(0x93B7BC, 0x93B8AB, 0x01C8, 2)])
    monkeypatch.setattr(lz, "decompress", lambda *a, **k: bytes(buf))
    for name in ("RECORD_LISTS", "ROW_TABLES", "COUNTED_LISTS", "EXTRA_ROWS"):
        monkeypatch.setattr(labels, name, [])
    rows = {r["id"]: r for r in labels.extract(bytes(rom))}
    g = rows["grid_00"]
    assert (g["bank"], g["top"], g["bottom"], g["n"], g["x"], g["y"], g["japanese"]) == \
        ("11", "%04X" % (0x8000 + table % 0x8000 + 8), "%04X" % (0x8000 + table % 0x8000 + 16), labels.GRID_CELLS, 14, 8, "花園")
    m = rows["mvn_0820D0_00"]
    assert (m["bank"], m["top"], m["bottom"], m["n"], m["japanese"]) == ("10", "A105", "A10B", 3, "打")
    t = rows["map_93B7BC_01C8"]
    assert (t["bank"], t["top"], t["bottom"], t["n"], t["x"], t["y"], t["japanese"]) == ("7F", "01C8", "0208", 2, 4, 7, "次")
    assert labels.row_words(bytes(rom), t, "bottom")[0] == 0x2C00 | n[2]


def test_label_table_narrow_flag_and_sites():
    from tools.kbb import build, encode
    rows = [{"id": "site_1", "bank": "10", "top": "A000", "bottom": "A010", "n": 2, "korean": "가"},
            {"id": "grid_00", "bank": "11", "top": "C493", "bottom": "C49B", "n": 4, "korean": "나다"},
            {"id": "map_93B7BC_01C8", "bank": "7F", "top": "01C8", "bottom": "0208", "n": 2, "korean": "라"}]
    gs = encode.GlyphSet([r["korean"] for r in rows])
    tab = build.label_table(rows, gs)
    p0, p1, p2 = struct.unpack_from("<3H", tab, 0)
    assert tab[p0 - 0xC000] != 1 and tab[p1 - 0xC000] == 1 and tab[p2 - 0xC000] != 1
    sites = build.label_sites(rows)
    assert struct.unpack_from("<H", sites, 0)[0] == 4                       # the bank-7F row has no site
    assert struct.unpack_from("<BHH", sites, 2) == (0x10, 0xA000, 0)
    assert struct.unpack_from("<BHH", sites, 7) == (0x10, 0xA010, build.LABEL_ROW_BOTTOM)
    assert struct.unpack_from("<BHH", sites, 12) == (0x11, 0xC493, 1)


def test_maplabel_table(monkeypatch):
    from tools.kbb import build, labels
    rows = [{"id": "x", "bank": "10", "top": "A000", "bottom": "A010", "n": 2, "korean": "가"},
            {"id": "map_93B7BC_01C8", "bank": "7F", "top": "01C8", "bottom": "0208", "n": 12, "korean": "다음"}]
    monkeypatch.setattr(labels, "row_words", lambda rom, r, key: (0x2E80, 0x2E81))
    tab = build.maplabel_table(b"", rows)
    assert struct.unpack("<5H", tab) == (1, 0x01C8, 0x2E80, 12, 1)

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


def test_roster_hooks_and_shift_table():
    from tools.kbb import encode
    sites = {p[0]: p for p in build.patches({"story": 0x9A22, "surname": 0x8018, "name_extra2": 0x87D5, "item": 0x8A27, "school": 0x99A2})}
    assert sites[0x016A8B][1] == b"\xAD\x9D\x71\x0A" and sites[0x016A8B][2] == build.jml(build.ENTRY_ROSTER_NAME)
    assert sites[0x016B2F][2] == build.jml(build.ENTRY_ROSTER_SHIFT)
    assert sites[0x016ADD][2] == build.jml(build.ENTRY_ROSTER_ITEM)
    assert sites[0x014300][2] == build.jml(build.ENTRY_ROSTER_W4) and sites[0x0142E4][2] == b"\xF4\xB0\x00"
    assert sites[0x0142ED][2] == b"\xBF\x80\xBD\xB1"
    assert sites[0x08395D][2] == build.jml(build.ENTRY_ROSTER_FULL) and sites[0x081456][2] == build.jml(build.ENTRY_ROSTER_FULL7F)
    assert sites[build.QUEUE_ROM][1] == b"\x08\x8B\xF4\x7E\x00" and sites[build.QUEUE_ROM][2][:4] == build.jml(build.ENTRY_QUEUE)
    assert len(build.MENU_POOL) == 95 and 0x0D not in build.MENU_POOL and all(t & 0xF >= 9 for t in build.MENU_POOL)
    rows = [{"korean": "내야"}, {"korean": "외야"}]
    gs = encode.GlyphSet([r["korean"] for r in rows])
    tab = build.shift_table(rows, gs)
    p0, p1 = struct.unpack_from("<II", tab, 0)
    assert p0 == 0xBD00 + 8 and p1 == p0 + len(gs.encode("내야"))
    assert tab[8:8 + len(gs.encode("내야"))] == gs.encode("내야")


def test_static8_rows_use_fixed_slots_and_original_tiles():
    from tools.kbb import font, static8
    rom = bytearray(font.FONT_OFFSET + font.FONT_SIZE)
    struct.pack_into("<9H", rom, 0x100, *([0x20BA] * 9))
    struct.pack_into("<3H", rom, 0x200, 0x204F, 0x202F, 0x209F)
    slots = static8.apply(rom, [{"offset": "100", "n": "9", "korean": "투수(1)"},
                                {"offset": "200", "n": "3", "korean": "수 "}])
    words = struct.unpack_from("<9H", rom, 0x100)
    assert words[0] == 0x2000 | slots["투"] and words[1] == 0x2000 | slots["수"]
    assert words[2:5] == (0x2082, 0x2013, 0x2092) and words[5:] == (0x2000,) * 4
    assert struct.unpack_from("<3H", rom, 0x200) == (0x2000 | slots["수"], 0x2000, 0x2000)
    assert set(slots.values()) <= set(static8.SLOTS) and not (set(slots.values()) & set(build.MENU_POOL))
    t = slots["투"]
    assert rom[font.FONT_OFFSET + t * 16:font.FONT_OFFSET + t * 16 + 16] == static8.font8.tile8("투")


def test_rows8_extract_pair_tables(monkeypatch):
    from tools.kbb import rows8
    rom = bytearray(0x20000)
    ptrs, sizes = 0x10100, 0x10200
    struct.pack_into("<HH", rom, ptrs, 0x8300, 0x8310)          # team 0: marks row, kana row
    struct.pack_into("<H", rom, sizes, 6)                        # 3 cells
    struct.pack_into("<3H", rom, 0x10300, 0x2000, 0x20EB, 0x2000)
    struct.pack_into("<3H", rom, 0x10310, 0x2000 | 0x1D, 0x2000 | 0x2D, 0x2000)
    monkeypatch.setattr(rows8, "PAIR_TABLES", [(ptrs, sizes, 1)])
    monkeypatch.setattr(rows8, "RECORD_REGIONS", [])
    rows = rows8.extract(bytes(rom), banks=())
    assert [(r["id"], r["n"], r["japanese"]) for r in rows] == [("q_028300", 3, "(marks)"), ("q_028310", 3, "あい_")]


def test_rows8_table_layout():
    from tools.kbb import encode, rows8
    rows = [{"bank": "10", "addr": "B25A", "n": 3, "korean": "수비"},
            {"bank": "10", "addr": "AE08", "n": 5, "korean": "포지션"},
            {"bank": "10", "addr": "B260", "n": 3, "korean": " "}, {"bank": "10", "addr": "0000", "n": 1, "korean": ""}]
    gs = encode.GlyphSet([r["korean"] for r in rows])
    tab = rows8.build_table(rows, gs, 0xA000)
    count = struct.unpack_from("<H", tab, 0)[0]
    assert count == 3
    e = [struct.unpack_from("<BHH", tab, 2 + 5 * i) for i in range(3)]
    assert [x[1] for x in e] == [0xAE08, 0xB25A, 0xB260]                # sorted by address
    assert e[0][2] == 0xA000 + 2 + 15 and tab[17:17 + len(gs.encode("포지션"))] == gs.encode("포지션")
    assert tab[e[2][2] - 0xA000] == 0                                      # blank row = empty string


def test_kanji16_two_syllable_glyph():
    from tools.kbb import font, kanji16
    rom = bytearray(font.FONT_OFFSET + font.FONT_SIZE)
    build.korean_kanji16(rom)
    rows = font.glyph16(rom, kanji16.KANJI16.index("選"))
    assert any(3 in r[:8] for r in rows) and any(3 in r[8:] for r in rows)   # 선 | 수 side by side
    assert all(rows[2 * y] == rows[2 * y + 1] for y in range(8))            # stretched 2x vertically


def test_sprtext_table_and_codec():
    from tools.kbb import sprtext
    rows = [[(x * y) % 16 for x in range(8)] for y in range(8)]
    assert sprtext.decode4(sprtext.encode4(rows)) == rows
    sig = bytes(range(32))
    row = {"korean": "열", "tl": sig.hex(), "tr": "00" * 32, "bl": sig.hex(), "br": (b"\x01" * 32).hex()}
    tab = sprtext.build_table([row])
    assert struct.unpack_from("<H", tab, 0)[0] == 3                # the all-zero quadrant is skipped
    bits = sprtext.first_word_bitmap(tab)
    assert len(bits) == 0x2000
    words = {struct.unpack_from("<H", tab, 2 + 64 * i)[0] for i in range(3)}
    assert all(bits[w >> 3] & (1 << (w & 7)) for w in words)
    assert not any(bits[w >> 3] & (1 << (w & 7)) for w in range(0x10000) if w not in words)
    assert tab[2:34] == sig
    rep = sprtext.decode4(tab[34:66])
    assert {v for r in rep for v in r} <= {sprtext.BG, sprtext.INK} and any(sprtext.INK in r for r in rep)
    sites = {p[0]: p for p in build.patches({"story": 0x9A22, "surname": 0x8018, "name_extra2": 0x87D5, "item": 0x8A27, "school": 0x99A2})}
    assert sites[build.SHEET_HOOK_ROM][2] == build.jml(build.ENTRY_SHEET)


def test_titlecard_draws_into_listed_tiles_only():
    from tools.kbb import sprtext, titlecard
    rom = bytearray(titlecard.TILESET_ROM + 0x4000)
    rows = [{"id": "t", "korean": "편", "top": "36a - 36c", "bottom": "37a 37b 37c"}]
    assert titlecard.apply(rom, rows) == 1
    def tile(t):
        off = titlecard.TILESET_ROM + (t - titlecard.FIRST_TILE) * 32
        return sprtext.decode4(rom[off:off + 32])
    assert all(v == 0 for r in tile(0x36b) for v in r)                       # '-' column untouched
    drawn = [v for t in (0x36a, 0x36c, 0x37a, 0x37b, 0x37c) for r in tile(t) for v in r]
    assert set(drawn) <= {titlecard.INK, titlecard.BG} and titlecard.INK in drawn


def test_lz_decompressor_runs_and_backrefs():
    from tools.kbb import lz
    # stream: run of 1 byte repeated twice -> AA AA ; run of 2 bytes once -> 01 02 ; back-ref 3 bytes at dict+1
    rom = bytearray(0x100)
    dictionary = 0x80
    rom[dictionary:dictionary + 4] = b"\x10\x11\x12\x13"
    stream = bytes([0x21, 0xAA, 0x12, 0x01, 0x02, 0x80, 0x01, 0x00])
    rom[0:len(stream)] = stream
    assert lz.decompress(rom, 0, dictionary) == b"\xAA\xAA\x01\x02\x11\x12\x13"


def test_title_logo_never_writes_the_shared_blank_tile():
    from tools.kbb import titlelogo
    used = [titlelogo.line_tile(b, r, c)
            for b in titlelogo.BLOCKS for r in range(b["rows"]) for c in range(b["cols"])]
    assert len(used) == len(set(used))                       # every cell has its own tile
    assert set(used).isdisjoint(titlelogo.SHARED_TILES)      # background blank tile stays intact


def test_no_task_yield_from_nested_code():
    # The game's task switcher ($80:EC8A) pops exactly its own frame and expects the stack
    # back at $1FFF, so yielding from inside our nested calls corrupts it and crashes.
    src = open("tools/kbb/asm/text.s", encoding="utf-8").read()
    assert "jsl TASK_WAIT" not in src


def test_game_over_syllables_sit_on_nine_tiles_each():
    from tools.kbb import titlelogo
    blocks = titlelogo.GAMEOVER["blocks"]
    letters = [c for c in titlelogo.GAMEOVER["text"] if c != " "]
    assert len(blocks) == 9 * len(letters)
    assert len(set(blocks)) == len(blocks)


def test_game_over_tiles_keep_off_the_victory_banners():
    # Until v0.6.5 the game over line took four runs of nine tiles that ran straight through the
    # banners of the victory screen, which shares this sheet: it rubbed out 勝 and で.
    from tools.kbb import titlelogo
    banners = {off // 32 for off in titlelogo.victory()}
    assert banners.isdisjoint(titlelogo.GAMEOVER["blocks"])
    assert banners.isdisjoint(titlelogo.THANKS["tiles"])
    assert set(titlelogo.GAMEOVER["blocks"]).isdisjoint(titlelogo.THANKS["tiles"])


def test_victory_banners_cover_whole_tiles_in_their_own_colours():
    from tools.kbb import sprtext, titlelogo
    tiles = titlelogo.victory()
    for b in titlelogo.BANNERS:
        want = {((b["row"] + r) * 16 + b["col"] + c) * 32
                for r in range(b["rows"]) for c in range(2)}
        assert want <= set(tiles)
        colours = {v for off in want for row in sprtext.decode4(tiles[off]) for v in row}
        assert colours <= {b["back"]} | {ink for _, ink in b["ink"]}
        assert colours != {b["back"]}                     # something was actually drawn
    assert all(len(d) == 32 for d in tiles.values())


def test_banner_glyph_fills_its_box():
    from tools.kbb import titlelogo
    g = titlelogo.banner_glyph("축", 13, 13)
    assert len(g) == 13 and all(len(r) == 13 for r in g)
    assert any(g[0]) and any(g[-1])                       # ink touches top and bottom
    assert any(r[0] for r in g) and any(r[-1] for r in g)  # and both sides
