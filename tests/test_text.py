from tools.kbb import table as T
from tools.kbb.text import decode, snes_to_rom


def test_menu_message_decodes():
    data = bytes.fromhex("28fed0dd3b09d04a9e02eddf0e8d6c02cd3e6d7fa002fdafd0fdaf6c024d7fdfd03e8dd00ebd2d8e1800")
    text, end = decode(data, 0)
    assert text == "「まずモードの せんたくを してから\n それぞれを えらんでくださいね。"
    assert end == len(data)


def test_handakuten_and_small_tsu():
    # e0 ba = ピ, f8 = ッ, 1a = チ
    text, _ = decode(bytes([0xE0, 0xBA, 0xF8, 0x1A, 0x00]), 0)
    assert text == "ピッチ"


def test_variable_and_pause_are_marked():
    text, _ = decode(bytes([0xF0, 0x42, 0xF3, 0x00]), 0)
    assert text == "{VAR:42}{PAUSE}"


def test_unknown_byte_is_shown_as_hex():
    text, _ = decode(bytes([0x10, 0x00]), 0)
    assert text == "{10}"


def test_snes_to_rom_lorom():
    assert snes_to_rom(0x06, 0xB542) == 0x033542


def test_table_has_no_duplicate_kana():
    kana = [ch for code, ch in T.TABLE.items() if "぀" <= ch <= "ヿ" and ch not in "゛゜"]
    assert len(kana) == len(set(kana)), [k for k in kana if kana.count(k) > 1]


def test_table_directory_counts_from_first_pointer():
    from tools.kbb.text import table_directory, BANK_START
    rom = bytearray(0x40000)
    # directory: two tables at $8018 and $8030
    rom[BANK_START:BANK_START + 4] = (0x8018).to_bytes(2, "little") + (0x8030).to_bytes(2, "little")
    rom[BANK_START + 0x18:BANK_START + 0x1A] = (0x8020).to_bytes(2, "little")   # 2 entries
    rom[BANK_START + 0x30:BANK_START + 0x32] = (0x8034).to_bytes(2, "little")   # 1 entry
    d = table_directory(bytes(rom))
    assert d[0] == ("surname", BANK_START + 0x18, 2)
    assert d[1] == ("name_extra1", BANK_START + 0x30, 1)
