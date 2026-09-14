"""Encode translated (or fallback) text for the new renderer.

Byte format (see asm/text.s):
  00        end of string
  02        space (the renderer word-wraps at spaces)
  A0        line break
  F0 xx     variable substitution (kept from the original script)
  03..7F    1-byte glyph code
  80..9F xx 2-byte glyph code: index = 0x80 + ((b0 & 0x1F) << 8 | xx)
"""
import collections
import re

from tools.kbb import glyphs

END, SPACE, NEWLINE, VARIABLE = 0x00, 0x02, 0xA0, 0xF0
ONE_BYTE_FIRST, ONE_BYTE_LAST = 0x03, 0x7F
TWO_BYTE_BASE = 0x80
MAX_GLYPHS = TWO_BYTE_BASE + 0x2000
VAR_RE = re.compile(r"\{VAR:([0-9A-Fa-f]{2})\}")


def tokens(text):
    """Split text into ('var', n) / ('nl',) / ('sp',) / ('ch', c) tokens."""
    out = []
    i = 0
    while i < len(text):
        m = VAR_RE.match(text, i)
        if m:
            out.append(("var", int(m.group(1), 16)))
            i = m.end()
            continue
        c = text[i]
        i += 1
        if c == "\n":
            out.append(("nl",))
        elif c == " " or c == "　":
            out.append(("sp",))
        else:
            out.append(("ch", c))
    return out


class GlyphSet:
    """Assigns glyph indices: the most frequent characters get 1-byte codes."""

    def __init__(self, texts):
        counts = collections.Counter()
        for t in texts:
            for tok in tokens(t):
                if tok[0] == "ch":
                    counts[tok[1]] += 1
        counts[glyphs.MISSING] += 0
        ranked = [c for c, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        self.index = {}
        one = ONE_BYTE_FIRST
        two = TWO_BYTE_BASE
        for c in ranked:
            if one <= ONE_BYTE_LAST:
                self.index[c] = one
                one += 1
            else:
                self.index[c] = two
                two += 1
        if two > MAX_GLYPHS:
            raise ValueError("too many distinct glyphs: %d" % len(ranked))
        self.count = max(two, ONE_BYTE_LAST + 1)
        self.chars = {v: k for k, v in self.index.items()}
        self.missing = []

    def code(self, ch):
        idx = self.index.get(ch)
        if idx is None:
            idx = self.index[glyphs.MISSING]
        if idx < TWO_BYTE_BASE:
            return bytes([idx])
        rel = idx - TWO_BYTE_BASE
        return bytes([TWO_BYTE_BASE | (rel >> 8), rel & 0xFF])

    def encode(self, text):
        out = bytearray()
        for tok in tokens(text):
            if tok[0] == "var":
                out += bytes([VARIABLE, tok[1]])
            elif tok[0] == "nl":
                out.append(NEWLINE)
            elif tok[0] == "sp":
                out.append(SPACE)
            else:
                out += self.code(tok[1])
        out.append(END)
        return bytes(out)

    def bitmaps(self, bdf=None):
        """(width table bytes, bitmap table bytes) indexed by glyph index."""
        bdf = bdf if bdf is not None else glyphs.load_bdf()
        widths = bytearray(self.count)
        bits = bytearray(self.count * glyphs.GLYPH_BYTES)
        missing = glyphs.render(glyphs.MISSING, bdf)
        for ch, idx in self.index.items():
            g = glyphs.render(ch, bdf)
            if g is None:
                self.missing.append(ch)
                g = missing
            w, cell = g
            widths[idx] = w
            bits[idx * glyphs.GLYPH_BYTES:(idx + 1) * glyphs.GLYPH_BYTES] = glyphs.pack(cell)
        return bytes(widths), bytes(bits)


def decode(data, gs):
    """Inverse of GlyphSet.encode, for tests and dumps."""
    out = []
    i = 0
    while i < len(data) and data[i] != END:
        b = data[i]
        if b == SPACE:
            out.append(" ")
            i += 1
        elif b == NEWLINE:
            out.append("\n")
            i += 1
        elif b == VARIABLE:
            out.append("{VAR:%02X}" % data[i + 1])
            i += 2
        elif b < TWO_BYTE_BASE:
            out.append(gs.chars[b])
            i += 1
        else:
            out.append(gs.chars[TWO_BYTE_BASE + ((b & 0x1F) << 8 | data[i + 1])])
            i += 2
    return "".join(out)


SPACE_W = 6


def layout(text, widths, max_px, max_lines=2):
    """Mirror the runtime word wrap. Returns a list of lines as (text, px) pairs;
    lines beyond max_lines are returned too so callers can report overflow."""
    def w(ch):
        return widths.get(ch, 12)
    lines = []
    cur, cur_px = "", 0
    words = []
    for tok in tokens(text):
        if tok[0] == "ch":
            if words and words[-1][0] == "word":
                words[-1] = ("word", words[-1][1] + tok[1])
            else:
                words.append(("word", tok[1]))
        elif tok[0] == "var":
            words.append(("word", "{VAR:%02X}" % tok[1]))
        else:
            words.append(tok)
    for k, tok in enumerate(words):
        if tok[0] == "nl":
            lines.append((cur, cur_px))
            cur, cur_px = "", 0
        elif tok[0] == "sp":
            nxt = words[k + 1] if k + 1 < len(words) else None
            nxt_px = sum(w(c) for c in nxt[1]) if nxt and nxt[0] == "word" and not nxt[1].startswith("{") else 0
            if cur_px + SPACE_W + nxt_px > max_px:
                lines.append((cur, cur_px))
                cur, cur_px = "", 0
            else:
                cur += " "
                cur_px += SPACE_W
        else:
            px = 0 if tok[1].startswith("{") else sum(w(c) for c in tok[1])
            cur += tok[1]
            cur_px += px
    lines.append((cur, cur_px))
    return lines


def check(texts, widths, max_px=248, max_lines=2):
    """Yield (id, lines) for strings that need more than max_lines at max_px."""
    for sid, text in texts.items():
        lines = layout(text, widths, max_px, max_lines)
        if len(lines) > max_lines or any(px > max_px for _, px in lines):
            yield sid, lines
