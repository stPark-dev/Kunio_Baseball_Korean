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
    "打": "타", "順": "순", "守": "수", "備": "비", "デ": "정", "タ": "보",
    "自": "아", "敵": "적", "チ": "군", "ム": " ",       # 自チーム / 敵チーム -> 아군 / 적군
    # two-character entries are drawn as two 8px syllables in one glyph cell
    "選": "선수", "手": " ",                               # 選手データ -> 선수 정보
    "の": " ", "相": "상대",
    "野": "야", "次": "유", "気": "기",                    # 응원 하위 메뉴의 [野次] / [気合] -> [야유] / [기합]
    "今": "이번", "ま": "까지", "で": "의", "成": "성", "績": "적",   # 今大会までの成績 -> 이번 대회까지의 성적
    "試": "시", "合": "합", "個": "개", "人": "인",
    "数": "수", "安": "안", "三": "삼", "振": "진", "盛": "도", "塁": "루", "本": "본",
    "失": "실", "策": "책", "登": "등", "板": "판", "御": "어", "被": "피", "審": "탈",
    "与": " ", "四": "사",                                # 与四球 -> 사구
    "防": "방", "率": "율", "工": "공", "実": "실", "業": "업", "高": "고", "校": "교",
    "商": "상", "全": "전", "米": "미", "学": "학원", "院": " ",   # 学院 -> 학원
    # school names (kun readings) as two 8px syllables per glyph; 園 follows 花園/夢園 (조노),
    # so 学園 reads 학원조노 and 谷花 reads 타니하나 - known compromises
    "花": "하나", "園": "조노", "宝": "호", "陵": "료", "霧": "키리", "雨": "사메",
    "白": "시라", "鷹": "타카", "冷": "레이", "峰": "호", "愛": "아이", "然": "젠",
    "明": "메이", "暗": "안", "黒": "코쿠", "龍": "류잔", "山": " ", "夢": "유메",
    "谷": "타니", "服": "핫토", "部": "리",
    "交": "교", "代": "대", "使": "사", "用": "용",       # 選手交代 / 守備交代 / 使用 (time-out menu)
}
# glyphs the reading table cannot name: アイテム is ア(0x07) + イテ(0x47) + ム(0x4F), and the
# time-out menu's 野次気合 uses its own glyphs 0x41-0x44 -> 응원
KOREAN16_IDX = {0x07: "아이", 0x47: "템", 0x41: "응", 0x42: "원", 0x43: " ", 0x44: " "}

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
