"""Rebuild the script bank (12 pointer tables + strings) in the new encoding.

The layout mirrors the original bank $06: a 24-byte directory of table addresses,
then each table (4-byte entries: u16 address, u16 0) immediately followed by its
strings. Tables are laid out in ascending address order like the original.
"""
import struct

from tools.kbb.text import TABLE_DIRECTORY_COUNT, table_directory

BANK_SIZE = 0x8000


def build_bank(rom, encoded):
    """encoded: {string id: bytes}. Returns (bank bytes, {table name: SNES address})."""
    directory = table_directory(rom)
    order = sorted(range(len(directory)), key=lambda k: directory[k][1])
    out = bytearray(TABLE_DIRECTORY_COUNT * 2)
    addr_of = {}
    for k in order:
        name, _, count = directory[k]
        table_addr = 0x8000 + len(out)
        addr_of[name] = table_addr
        entries = bytearray()
        strings = bytearray()
        base = table_addr + 4 * count
        for n in range(count):
            entries += struct.pack("<HH", base + len(strings), 0)
            strings += encoded["%s_%03d" % (name, n)]
        out += entries + strings
    if len(out) > BANK_SIZE:
        raise ValueError("script bank overflow: %d bytes" % len(out))
    for k, (name, _, _) in enumerate(directory):
        struct.pack_into("<H", out, 2 * k, addr_of[name])
    return bytes(out) + b"\xff" * (BANK_SIZE - len(out)), addr_of
