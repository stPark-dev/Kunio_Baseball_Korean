import struct

from tools.kbb.script import build_bank
from tools.kbb.text import BANK_START, TABLE_NAMES


def _fake_rom():
    rom = bytearray(0x40000)
    # 12 tables: table k at $8018 + k*8 with one entry each, strings right after
    addr = 0x8018
    for k in range(12):
        struct.pack_into("<H", rom, BANK_START + 2 * k, addr)
        struct.pack_into("<HH", rom, BANK_START + addr - 0x8000, addr + 4, 0)
        rom[BANK_START + addr - 0x8000 + 4] = 0
        addr += 8
    return bytes(rom)


def test_build_bank_layout():
    rom = _fake_rom()
    encoded = {"%s_000" % n: bytes([0x10 + k, 0]) for k, n in enumerate(TABLE_NAMES)}
    bank, addrs = build_bank(rom, encoded)
    assert len(bank) == 0x8000
    assert addrs["surname"] == 0x8018
    first_entry = struct.unpack_from("<HH", bank, 0x18)
    assert first_entry == (0x801C, 0)
    assert bank[0x1C:0x1E] == bytes([0x10, 0])
    assert struct.unpack_from("<H", bank, 0)[0] == 0x8018
