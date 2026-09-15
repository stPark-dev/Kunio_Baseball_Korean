"""In-game 8x8 word strings (pitch and swing names) at the end of bank $06.

Records of 28 bytes: header 0016 0001, 11 tile words (tile | $2000, $2002 = blank),
then the tilemap row offset. Usage: python -m tools.kbb.ingame ROM [ingame.csv]
"""
import csv
import os
import struct
import sys

from tools.kbb import table as T

RECORDS_START = 0x03708A
RECORD_SIZE = 28
RECORD_WORDS = 11
HEADER = (0x16, 1)
BLANK = 0x2002


def decode_words(words):
    out = ""
    for w in words:
        t = w & 0x3FF
        if t == 2:
            out += " "
        elif t in (0x21, 0x22):
            out += "゛"
        elif t in (0x11, 0x31):
            out += "゜"
        else:
            out += T.TABLE.get(t, "{%02x}" % t)
    return out.rstrip()


def records(rom):
    p = RECORDS_START
    out = []
    while p + RECORD_SIZE <= len(rom):
        if struct.unpack_from("<HH", rom, p) != HEADER:
            break
        words = struct.unpack_from("<%dH" % RECORD_WORDS, rom, p + 4)
        out.append({"id": "pitch_%03d" % len(out), "offset": "%06X" % p,
                    "japanese": decode_words(words), "korean": ""})
        p += RECORD_SIZE
    return out


def encode_record(rom, offset, text, static):
    """Overwrite a record's 11 words with static 8x8 tiles for `text`."""
    words = []
    for ch in text[:RECORD_WORDS]:
        if ch == " ":
            words.append(BLANK)
        elif ch in static:
            words.append(static[ch] | 0x2000)
        else:
            words.append(T.REVERSE.get(ch, 0x03) | 0x2000)   # digits / Latin keep their slots
    words += [BLANK] * (RECORD_WORDS - len(words))
    struct.pack_into("<%dH" % RECORD_WORDS, rom, offset + 4, *words)


def main():
    rom = open(sys.argv[1], "rb").read()
    rows = records(rom)
    if len(sys.argv) > 2:
        path = sys.argv[2]
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = {r["id"]: r["korean"] for r in csv.DictReader(f)}
            for r in rows:
                r["korean"] = old.get(r["id"], "")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id", "offset", "japanese", "korean"])
            w.writeheader()
            w.writerows(rows)
    for r in rows:
        print(r["id"], r["offset"], repr(r["japanese"]))


if __name__ == "__main__":
    main()
