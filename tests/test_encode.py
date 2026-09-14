import pytest

from tools.kbb import encode
from tools.kbb.encode import GlyphSet, decode, tokens


def test_tokens_split_vars_spaces_and_newlines():
    assert tokens("a {VAR:42}\nb") == [("ch", "a"), ("sp",), ("var", 0x42), ("nl",), ("ch", "b")]


def test_frequent_chars_get_one_byte_codes():
    gs = GlyphSet(["가가가 나"])
    assert gs.index["가"] == 0x03
    assert gs.index["나"] == 0x04
    assert gs.encode("가 나\n") == bytes([0x03, 0x02, 0x04, 0xA0, 0x00])


def test_two_byte_codes_after_125_glyphs():
    chars = [chr(0xAC00 + i) for i in range(130)]
    gs = GlyphSet(["".join(chars)])
    last = chars[-1]
    idx = gs.index[last]
    assert idx >= encode.TWO_BYTE_BASE
    data = gs.encode(last)
    assert data == bytes([0x80 | ((idx - 0x80) >> 8), (idx - 0x80) & 0xFF, 0x00])
    assert decode(data, gs) == last


def test_variable_and_missing_glyph():
    gs = GlyphSet(["가"])
    assert gs.encode("{VAR:45}") == bytes([0xF0, 0x45, 0x00])
    assert gs.encode("\U0001F600") == gs.encode("?")  # unknown char -> '?'


def test_bitmaps_tables_sized_by_glyph_count():
    gs = GlyphSet(["가나"])
    widths, bits = gs.bitmaps()
    assert len(widths) == gs.count and len(bits) == gs.count * 32
    assert widths[gs.index["가"]] == 12
    assert any(bits[gs.index["가"] * 32:(gs.index["가"] + 1) * 32])


def test_layout_wraps_at_spaces():
    from tools.kbb.encode import layout
    widths = {c: 12 for c in "가나다라마바사"}
    # 3 words of 36px + spaces: fits 2 per line at 90px
    lines = layout("가나다 라마바 사", widths, max_px=90)
    assert [l for l, _ in lines] == ["가나다 라마바", "사"]


def test_layout_honours_explicit_newline_and_reports_overflow():
    from tools.kbb.encode import check, layout
    widths = {"가": 12}
    lines = layout("가\n가\n가", widths, max_px=248)
    assert len(lines) == 3
    assert list(check({"x": "가\n가\n가", "y": "가"}, widths))[0][0] == "x"
