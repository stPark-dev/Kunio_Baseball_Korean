from tools.kbb.kana2ko import transliterate


def test_basic_names():
    assert transliterate("すがた") == "스가타"
    assert transliterate("いちじょう") == "이치조"
    assert transliterate("ななせ") == "나나세"
    assert transliterate("たちばな") == "타치바나"


def test_katakana_long_vowel_sokuon_and_n():
    assert transliterate("クリッシイ") == "쿠릿시이"
    assert transliterate("ゴードン") == "고돈"
    assert transliterate("はっとり") == "핫토리"
    assert transliterate("にった") == "닛타"
    assert transliterate("こんどう") == "콘도"
    assert transliterate("れいか") == "레이카"
    assert transliterate("ゆうじろう") == "유지로"


def test_small_kana():
    assert transliterate("きりがくれ") == "키리가쿠레"
    assert transliterate("ぎんぎんゼット") == "긴긴젯토"
    assert transliterate("フラッシュ") == "후랏슈"
    assert transliterate("テューク") == "튜쿠"
