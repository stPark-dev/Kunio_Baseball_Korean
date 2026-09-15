"""Reading of the 128 16x16 glyphs (tiles 0x100-0x2FF) used by menu labels.
Index n -> top-left tile 0x100 + (n // 8) * 0x20 + (n % 8) * 2. '?' marks glyphs
whose reading from the tile sheet is uncertain; they are only used to identify
labels for translation, never re-encoded."""

KANJI16 = list(
    "　率数白霧園然ア"
    "防御熱黒愛陵商敵"
    "投球花服血暗業チ"
    "本塁冷夢高龍雨ム"
    "明宝谷打校山実見"
    "先発火小全院鷹交"
    "変更順峰学部工代"
    "守備選手デタ自作"
    "戦???い会の行"
    "使・成振被第相ム"
    "用勝ち盛審回今0"
    "野負け失与後ま2"
    "次対績策死攻で4"
    "気個安登球練賞6"
    "合人三板四習品8"
    "決勝準!大試投米"
)
# Glyphs 0x2A/0x2B ("火小" above) are really the half-width pairs "メン"/"バー" of 先発メンバー,
# and 0x3C is "デー" of データ. Korean replacements drawn over the glyph bitmaps (image translation)
# for the screens whose text data is not located (VS title, pre-game menu). Sino-Korean readings
# are the same wherever a glyph appears, so one syllable per glyph is safe.
KOREAN16 = {
    "熱": "열", "血": "혈", "野": "야", "球": "구", "大": "대", "会": "회", "対": "대",
    "第": "제", "回": "회", "戦": "전",
    "先": "선", "発": "발", "火": "멤", "小": "버", "変": "변", "更": "경",
    "打": "타", "順": "순", "守": "수", "備": "비", "選": "선", "手": "수", "デ": "정", "タ": "보",
    "自": "아", "敵": "적", "チ": "군", "ム": " ",       # 自チーム / 敵チーム -> 아군 / 적군
}

# tiles 0x24E.. hold two digits per glyph: "01", "23", ...
DIGIT_PAIRS = {0x24E: "01", 0x26E: "23", 0x28E: "45", 0x2AE: "67", 0x2CE: "89"}


def tile_to_index(tile):
    """Top-left tile number -> glyph index, or None if not a 16x16 top-left tile."""
    if not 0x100 <= tile < 0x300:
        return None
    blk, within = (tile - 0x100) // 0x20, (tile - 0x100) % 0x20
    if within >= 0x10 or within % 2:
        return None
    return blk * 8 + within // 2
