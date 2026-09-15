"""Pre-drawn 8x8 rows in the menu font that are not labels (roster position names,
やめる/けってい, dakuten mark rows). The rows are word lists in ROM; their Korean text is
drawn with Galmuri7 into fixed menu-font slots (columns 8 and C, the small-kana tiles),
so they survive the dynamic kana-column pool used for player names."""
import struct

from tools.kbb import font, font8, table

SLOTS = [t for t in range(0x18, 0x100, 0x10)] + [t for t in range(0x0C, 0x100, 0x10)]
BLANK = 0x00


class Static8Error(Exception):
    pass


def _ascii():
    inv = {}
    for k, v in table.TABLE.items():
        if v and v not in inv:
            inv[v] = k
    return inv


def encode_row(text, n, attr, slots):
    """Word list of n cells for text; Hangul syllables take slots from the dict (allocating
    new ones), other characters use the original font tiles."""
    inv = _ascii()
    words = []
    for ch in text:
        if ch == " ":
            t = BLANK
        elif ch in inv:
            t = inv[ch]
        else:
            if ch not in slots:
                if len(slots) >= len(SLOTS):
                    raise Static8Error("out of static 8x8 slots at %r" % ch)
                slots[ch] = SLOTS[len(slots)]
            t = slots[ch]
        words.append(attr | t)
    if len(words) > n:
        raise Static8Error("row too long (%d > %d cells): %s" % (len(words), n, text))
    return words + [attr | BLANK] * (n - len(words))


def apply(rom, rows):
    """Rewrite each row (offset, n, korean) in place and draw the slot glyphs; returns {char: slot}."""
    slots = {}
    for r in rows:
        if not r.get("korean"):
            continue
        off, n = int(r["offset"], 16), int(r["n"])
        attr = struct.unpack_from("<H", rom, off)[0] & 0xFC00
        struct.pack_into("<%dH" % n, rom, off, *encode_row(r["korean"], n, attr, slots))
    for ch, t in slots.items():
        data = font8.tile8(ch)
        if data is None:
            raise Static8Error("no 8px glyph for %r" % ch)
        rom[font.FONT_OFFSET + t * 16:font.FONT_OFFSET + t * 16 + 16] = data
    return slots
