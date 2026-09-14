from tools.kbb.dis65816 import disassemble, rom_to_snes


def test_rom_to_snes_lorom():
    assert rom_to_snes(0x086A57) == 0x10EA57
    assert rom_to_snes(0x000000) == 0x008000


def test_rep_sep_change_immediate_size():
    code = bytes.fromhex("c220 a93412 e220 a956 60")
    out = [t for _, _, _, t in disassemble(code, 0, len(code))]
    assert out == ["REP #$20", "LDA #$1234", "SEP #$20", "LDA #$56", "RTS"]


def test_branch_targets_are_absolute():
    code = bytes.fromhex("d0fe")  # BNE to itself
    (_, _, _, text), = disassemble(code, 0, 2)
    assert text == "BNE $008000"


def test_block_move_operand_order():
    (_, _, _, text), = disassemble(bytes.fromhex("547e16"), 0, 3)
    assert text == "MVN $16,$7E"
