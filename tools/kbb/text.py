"""Decode game text from the ROM.

Bank 0x06 (ROM 0x030000-0x037FFF) holds the script. The bank starts with a directory of
12 u16 addresses, each pointing at a pointer table. A pointer table is a list of 4-byte
entries: u16 offset (SNES $06:xxxx, LoROM) followed by u16 zero.
"""
import csv
import struct

from tools.kbb import table as T

TEXT_BANK = 0x06

BANK_START = TEXT_BANK * 0x8000
TABLE_DIRECTORY_COUNT = 12     # u16 SNES addresses at the top of the bank

# Names for the 12 tables, in directory order (contents identified from the strings)
TABLE_NAMES = ["surname", "name_extra1", "name_extra2", "name_set3", "name_set4",
               "name_set5", "item", "story", "name_set6", "fullname", "staff", "school"]


def table_directory(rom):
    """Return [(name, rom_offset, count)] for the pointer tables listed in the bank header.

    Each table is immediately followed by its strings, so its entry count is
    (first pointer - table address) / 4.
    """
    out = []
    for k in range(TABLE_DIRECTORY_COUNT):
        addr = struct.unpack_from("<H", rom, BANK_START + 2 * k)[0]
        toff = snes_to_rom(TEXT_BANK, addr)
        first = struct.unpack_from("<H", rom, toff)[0]
        out.append((TABLE_NAMES[k], toff, (first - addr) // 4))
    return out


def snes_to_rom(bank, addr):
    return bank * 0x8000 + (addr - 0x8000)


def decode(data, offset):
    """Decode one string starting at `offset`. Returns (text, end_offset)."""
    out = []
    i = offset
    while i < len(data):
        b = data[i]
        i += 1
        if b == T.END:
            break
        if b == T.SPACE:
            out.append(" ")
        elif b == T.NEWLINE:
            out.append("\n")
        elif b in (T.DAKUTEN, T.HANDAKUTEN):
            mark = "゙" if b == T.DAKUTEN else "゚"
            base = T.TABLE.get(data[i], "{%02X}" % data[i])
            i += 1
            out.append(T.voiced(base, mark))
        elif b == T.VARIABLE:
            out.append("{VAR:%02X}" % data[i])
            i += 1
        elif b in T.TABLE:
            out.append(T.TABLE[b])
        else:
            out.append("{%02X}" % b)
    return "".join(out), i


def read_pointers(rom, table_offset, count):
    return [struct.unpack_from("<HH", rom, table_offset + 4 * k)[0] for k in range(count)]


def extract(rom):
    """Yield dicts for every string in every known pointer table."""
    for name, toff, count in table_directory(rom):
        for k, ptr in enumerate(read_pointers(rom, toff, count)):
            off = snes_to_rom(TEXT_BANK, ptr)
            text, end = decode(rom, off)
            yield {"id": "%s_%03d" % (name, k), "table": name, "offset": "%06X" % off,
                   "length": end - off, "japanese": text, "korean": ""}


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "table", "offset", "length", "japanese", "korean"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    import sys
    rom = open(sys.argv[1], "rb").read()
    rows = list(extract(rom))
    write_csv(rows, sys.argv[2])
    print(len(rows), "strings ->", sys.argv[2])
