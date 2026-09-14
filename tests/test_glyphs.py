from tools.kbb import glyphs


def test_render_hangul_metrics():
    bdf = glyphs.load_bdf()
    w, cell = glyphs.render("가", bdf)
    assert w == 12
    assert len(cell) == 16
    ink = [y for y, v in enumerate(cell) if v]
    assert ink[0] >= 2 and ink[-1] <= 13          # 11px glyph sits above the baseline row 14
    assert all((v & 0x000F) == 0 for v in cell)   # never wider than 12px


def test_render_missing_returns_none():
    assert glyphs.render("\U0001F600") is None


def test_pack_unpack_roundtrip():
    cell = [(i * 0x1111) & 0xFFFF for i in range(16)]
    assert glyphs.unpack(glyphs.pack(cell)) == cell
    assert glyphs.pack(cell)[:2] == b"\x00\x00" and glyphs.pack([0x8000] + [0] * 15)[:2] == b"\x00\x80"
