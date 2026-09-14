"""Character table for the 8x8 text font (VRAM tiles 0x00-0xFF).

Text bytes are tile indices into the 8x8 font at ROM 0x0B47E5 (2bpp, 256 tiles),
except for a handful of control codes (see CONTROL). Voiced kana are written as a
prefix byte (DAKUTEN / HANDAKUTEN) followed by the base kana.
"""
import unicodedata

END = 0x00
SPACE = 0x02
NEWLINE = 0xA0
DAKUTEN = 0xD0
HANDAKUTEN = 0xE0
VARIABLE = 0xF0    # followed by one byte: name/number substitution
PAUSE = 0xF3

CONTROL = {END, SPACE, NEWLINE, DAKUTEN, HANDAKUTEN, VARIABLE, PAUSE}

# Columns 0x_9/0x_A/0x_B: katakana, 0x_D/0x_E/0x_F: hiragana, 0x_8: small kana and
# punctuation, 0x_C: small hiragana (rows 7-F). Column 0 is blank (used by controls).
_KATA = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワン"
_HIRA = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわん"

TABLE = {}
for i in range(15):                          # rows 1..F
    TABLE[(i + 1) * 16 + 0x9] = _KATA[i]     # ア..ソ (0x09 is ー)
    TABLE[(i + 1) * 16 + 0xD] = _HIRA[i]     # あ..そ (0x0D is blank)
for i in range(16):                          # rows 0..F
    TABLE[i * 16 + 0xA] = _KATA[15 + i]      # タ..マ
    TABLE[i * 16 + 0xE] = _HIRA[15 + i]      # た..ま
for i in range(14):                          # rows 0..D
    TABLE[i * 16 + 0xB] = _KATA[31 + i]      # ミ..ン
    TABLE[i * 16 + 0xF] = _HIRA[31 + i]      # み..ん

TABLE.update({
    0x03: "0", 0x13: "1", 0x23: "2", 0x33: "3", 0x43: "4", 0x53: "5", 0x63: "6",
    0x73: "7", 0x83: "8", 0x93: "9", 0xA3: ":", 0xB3: ";", 0xC3: "<", 0xD3: "=", 0xE3: ">", 0xF3: "?",
    0x04: "@", 0x14: "A", 0x24: "B", 0x34: "C", 0x44: "D", 0x54: "E", 0x64: "F", 0x74: "G",
    0x84: "H", 0x94: "I", 0xA4: "J", 0xB4: "K", 0xC4: "L", 0xD4: "M", 0xE4: "N", 0xF4: "O",
    0x05: "P", 0x15: "Q", 0x25: "R", 0x35: "S", 0x45: "T", 0x55: "U", 0x65: "V", 0x75: "W",
    0x85: "X", 0x95: "Y", 0xA5: "Z", 0xB5: "[", 0xC5: "¥", 0xD5: "]", 0xE5: "^", 0xF5: "_",
    0x01: "゛", 0x06: "'", 0x11: "゜", 0x12: "!", 0x21: "“", 0x22: "”", 0x31: "°", 0x32: "#",
    0x18: "。", 0x28: "「", 0x38: "」", 0x48: "、", 0x58: "・", 0x68: "ヲ",
    0x78: "ァ", 0x88: "ィ", 0x98: "ゥ", 0xA8: "ェ", 0xB8: "ォ", 0xC8: "ャ", 0xD8: "ュ", 0xE8: "ョ", 0xF8: "ッ",
    0x6C: "を", 0x7C: "ぁ", 0x8C: "ぃ", 0x9C: "ぅ", 0xAC: "ぇ", 0xBC: "ぉ", 0xCC: "ゃ", 0xDC: "ゅ", 0xEC: "ょ", 0xFC: "っ",
    0x09: "ー", 0x72: "'", 0x82: "(", 0x92: ")", 0xB7: "♡", 0xC2: ",", 0xC7: "|", 0xD2: "-", 0xD7: "/",
    0xE2: ".", 0xE7: "~", 0xEB: "゛", 0xFB: "゜",
    # 8x8 kanji (reading from the tile sheet; ? = uncertain)
    0x07: "校", 0x16: "上", 0x17: "人", 0x26: "巧", 0x27: "体", 0x36: "強", 0x37: "気",
    0x41: "超", 0x42: "総", 0x46: "根", 0x51: "大", 0x52: "吸", 0x56: "性", 0x61: "球", 0x62: "弾",
    0x66: "功", 0x71: "速", 0x76: "撃", 0x81: "剛", 0x86: "砲", 0x91: "忍", 0x96: "法", 0xA1: "投",
    0xA2: "際", 0xA6: "術", 0xA7: "衆", 0xB1: "法", 0xB2: "波", 0xB6: "飛", 0xC1: "右", 0xC6: "剪",
    0xD1: "左", 0xD6: "新", 0xE1: "龍", 0xE6: "麗", 0xF1: "魔", 0xF2: "打", 0xF6: "君",
})
# The PAUSE control shares its byte with the "?" glyph slot; the control wins in text.
del TABLE[0xF3]

REVERSE = {ch: code for code, ch in TABLE.items()}


def voiced(base, mark):
    """Combine a kana with a (han)dakuten combining mark, e.g. voiced('か', '゙') -> 'が'."""
    return unicodedata.normalize("NFC", base + mark)
