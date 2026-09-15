"""Kana -> Hangul transliteration for names (player, umpire, school tables).

Uses the everyday fan-translation style (aspirated k/t everywhere: か=카, た=타),
which matches the character names used in the dialogue translation.
"""
import unicodedata

_ROWS = {
    "a": "ㅏ", "i": "ㅣ", "u": "ㅜ", "e": "ㅔ", "o": "ㅗ",
}
# kana -> (onset, vowel) using romaji-like keys
_BASE = {
    "あ": ("", "a"), "い": ("", "i"), "う": ("", "u"), "え": ("", "e"), "お": ("", "o"),
    "か": ("k", "a"), "き": ("k", "i"), "く": ("k", "u"), "け": ("k", "e"), "こ": ("k", "o"),
    "さ": ("s", "a"), "し": ("sh", "i"), "す": ("s", "u"), "せ": ("s", "e"), "そ": ("s", "o"),
    "た": ("t", "a"), "ち": ("ch", "i"), "つ": ("ts", "u"), "て": ("t", "e"), "と": ("t", "o"),
    "な": ("n", "a"), "に": ("n", "i"), "ぬ": ("n", "u"), "ね": ("n", "e"), "の": ("n", "o"),
    "は": ("h", "a"), "ひ": ("h", "i"), "ふ": ("h", "u"), "へ": ("h", "e"), "ほ": ("h", "o"),
    "ま": ("m", "a"), "み": ("m", "i"), "む": ("m", "u"), "め": ("m", "e"), "も": ("m", "o"),
    "や": ("y", "a"), "ゆ": ("y", "u"), "よ": ("y", "o"),
    "ら": ("r", "a"), "り": ("r", "i"), "る": ("r", "u"), "れ": ("r", "e"), "ろ": ("r", "o"),
    "わ": ("w", "a"), "を": ("", "o"),
    "が": ("g", "a"), "ぎ": ("g", "i"), "ぐ": ("g", "u"), "げ": ("g", "e"), "ご": ("g", "o"),
    "ざ": ("z", "a"), "じ": ("j", "i"), "ず": ("z", "u"), "ぜ": ("z", "e"), "ぞ": ("z", "o"),
    "だ": ("d", "a"), "ぢ": ("j", "i"), "づ": ("z", "u"), "で": ("d", "e"), "ど": ("d", "o"),
    "ば": ("b", "a"), "び": ("b", "i"), "ぶ": ("b", "u"), "べ": ("b", "e"), "ぼ": ("b", "o"),
    "ぱ": ("p", "a"), "ぴ": ("p", "i"), "ぷ": ("p", "u"), "ぺ": ("p", "e"), "ぽ": ("p", "o"),
}
# Hangul syllables for onset+vowel (simple vowels)
_SYL = {
    "": "아이우에오", "k": "카키쿠케코", "s": "사시스세소", "sh": "샤시슈셰쇼", "t": "타치츠테토",
    "ch": "차치추체초", "ts": "차치츠체초", "n": "나니누네노", "h": "하히후헤호", "m": "마미무메모",
    "y": "야이유예요", "r": "라리루레로", "w": "와이우웨오", "g": "가기구게고", "z": "자지즈제조",
    "j": "자지주제조", "d": "다지즈데도", "b": "바비부베보", "p": "파피푸페포",
}
_VI = {"a": 0, "i": 1, "u": 2, "e": 3, "o": 4}
# palatalised: onset + small ya/yu/yo
_YA = {
    "k": "캬큐쿄", "sh": "샤슈쇼", "ch": "차추초", "n": "냐뉴뇨", "h": "햐휴효", "m": "먀뮤묘",
    "r": "랴류료", "g": "갸규교", "j": "자주조", "b": "뱌뷰뵤", "p": "퍄퓨표",
    "t": "탸튜툐", "d": "댜듀됴", "z": "쟈쥬죠", "s": "샤슈쇼",
}
_SMALL_Y = {"ゃ": 0, "ゅ": 1, "ょ": 2}
_SMALL_V = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}


def _to_hira(text):
    out = []
    for ch in text:
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:
            out.append(chr(o - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _add_batchim(syl, jamo):
    """Attach a final consonant (ㄴ or ㅅ) to a precomposed Hangul syllable."""
    code = ord(syl) - 0xAC00
    if code < 0 or code > 11171:
        return syl + jamo
    final = {"ㄴ": 4, "ㅅ": 19}[jamo]
    return chr(0xAC00 + (code // 28) * 28 + final)


def transliterate(text):
    text = _to_hira(unicodedata.normalize("NFC", text))
    out = []
    last_v = ""
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch == "ー":
            i += 1
            continue
        if ch == "う" and last_v in ("o", "u"):      # long vowel: こう -> 코, ゆう -> 유
            i += 1
            continue
        if ch == "っ":
            if out and out[-1] and "가" <= out[-1][-1] <= "힣":
                out[-1] = out[-1][:-1] + _add_batchim(out[-1][-1], "ㅅ")
            i += 1
            continue
        if ch == "ん":
            if out and out[-1] and "가" <= out[-1][-1] <= "힣":
                out[-1] = out[-1][:-1] + _add_batchim(out[-1][-1], "ㄴ")
            else:
                out.append("ㄴ")
            i += 1
            continue
        if ch in _BASE:
            onset, vowel = _BASE[ch]
            if nxt in _SMALL_Y and onset in _YA:
                out.append(_YA[onset][_SMALL_Y[nxt]])
                last_v = "aou"[_SMALL_Y[nxt]]
                i += 2
                continue
            if nxt in _SMALL_V:                      # ふぁ, てぃ, うぃ ...
                v = _SMALL_V[nxt]
                if ch == "ふ":
                    out.append("파피푸페포"[_VI[v]])
                elif ch == "う":
                    out.append("와위우웨워"[_VI[v]])
                elif ch == "て":
                    out.append("타티투테토"[_VI[v]])
                elif ch == "で":
                    out.append("다디두데도"[_VI[v]])
                else:
                    out.append(_SYL[onset][_VI[v]])
                i += 2
                continue
            out.append(_SYL[onset][_VI[vowel]])
            last_v = vowel
            i += 1
            continue
        out.append(ch)
        last_v = ""
        i += 1
    return "".join(out)
