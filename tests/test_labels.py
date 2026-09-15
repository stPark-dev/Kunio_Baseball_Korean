from tools.kbb.labels import decode_rows, pair_rows


def test_decode_rows_kana_with_dakuten_and_kanji():
    # top row: dakuten over the 2nd cell, then a 16x16 glyph (熱 = tiles 124/125 over 134/135)
    top = [0x002, 0x001, 0x124, 0x125]
    bot = [0x0AE, 0x0CD, 0x134, 0x135]
    assert decode_rows(top, bot) == "はじ熱"


def test_pair_rows_matches_top_and_bottom_calls():
    top = {"site": 1, "bank": 0x11, "addr": 0x8000, "n": 4, "x": 3, "y": 9}
    bot_iny = {"site": 2, "bank": 0x11, "addr": 0x8008, "n": 4, "x": 3, "y": 9}
    other = {"site": 3, "bank": 0x11, "addr": 0x8010, "n": 6, "x": 3, "y": 9}
    pairs = pair_rows([top, bot_iny, other])
    assert pairs == [(top, bot_iny)]
