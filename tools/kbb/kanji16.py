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
