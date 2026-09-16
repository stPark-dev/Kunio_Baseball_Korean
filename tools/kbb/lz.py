"""Port of the scene graphics decompressor at $91:AB43 (script command 16).

Stream of control bytes read from the source bank:
  0x00            end
  0xxxxxxx (b7=0) run: length |= b & 0x0F, repeat |= (b >> 4) & 7; the next `length` stream bytes
                  are written `repeat` times (the game's MVN loop reloads only the source pointer)
  10xxxxxx (b7=1) back reference: 2 bytes, count = ((b0 >> 4) & 3) + 3, offset = ((b0 & 0x0F) << 8) | b1,
                  copied from a fixed dictionary (the record's third address, same bank as the stream)
  11xxxxxx        extension: length = (length << 3) | ((b & 7) << 4), repeat = (repeat << 3) | (b & 0x38)
The record is: cmd 16, dest (3), source (3), dictionary (3)."""
import re
import struct

CMD = 0x16
DEST_SPRITES = 0x7FB000


def snes_to_rom(addr):
    return ((addr >> 16) & 0x3F) * 0x8000 + ((addr & 0xFFFF) - 0x8000)


def decompress(rom, src, dictionary, limit=0x10000):
    """Decompress the stream at ROM offset `src` with the dictionary at ROM offset `dictionary`."""
    out = bytearray()
    length = repeat = 0
    p = src
    while len(out) < limit:
        b = rom[p]
        if b == 0:
            break
        if b & 0x80 == 0:
            length |= b & 0x0F
            repeat |= (b >> 4) & 7
            p += 1
            out += rom[p:p + length] * (repeat or 0x10000)
            p += length
            length = repeat = 0
        elif b & 0x40 == 0:
            count = ((b >> 4) & 3) + 3
            offset = ((b & 0x0F) << 8) | rom[p + 1]
            p += 2
            out += rom[dictionary + offset:dictionary + offset + count]
            length = repeat = 0
        else:
            length = (length << 3) | ((b & 7) << 4)
            repeat = (repeat << 3) | (b & 0x38)
            p += 1
    return bytes(out[:limit])


def records(rom, banks=(0x00, 0x01)):
    """(rom offset of record, dest, source, dictionary) for every command-16 record in the script banks."""
    out = []
    for bank in banks:
        lo, hi = bank * 0x8000, (bank + 1) * 0x8000
        for m in re.finditer(rb"\x16(..[\x7e\x7f])(..[\x80-\xbf])(..[\x80-\xbf])", rom[lo:hi], re.S):
            dest, src, dic = (struct.unpack("<I", g + b"\0")[0] for g in m.groups())
            if (src >> 16) == (dic >> 16):
                out.append((lo + m.start(), dest, src, dic))
    return out
