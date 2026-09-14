"""Report BG/OBJ VRAM usage from a Snes9x savestate + VRAM dump (harness --dump-state/--dump-vram).

Usage: python -m tools.kbb.vramscan state.bin vram.bin
"""
import re
import struct
import sys


def ppu_regs(state):
    """Parse the PPU block of a Snes9x snapshot (big-endian fields)."""
    m = re.search(rb"PPU:(\d{6}):", state)
    blk = state[m.end():m.end() + int(m.group(1))]
    o = 14  # VMA (10) + WRAM (4)
    bgs = []
    for _ in range(4):
        sc, hoff, voff, size, name, scsize = struct.unpack_from(">HHHBHH", blk, o)
        bgs.append({"tilemap": sc * 2, "hoff": hoff, "voff": voff, "bgsize": size,
                    "namebase": name * 2, "scsize": scsize})
        o += 11
    mode, bg3prio = blk[o], blk[o + 1]
    o += 2 + 1 + 1 + 1 + 1 + 512  # CGFLIP CGFLIPRead CGADD CGSavedByte CGDATA
    o += 128 * 11                  # OBJ[128]: HPos(2) VPos(2) HFlip VFlip Name(2) Priority Palette Size
    o += 3                         # OBJThroughMain/Sub, OBJAddition
    objname, objsel, objsize = struct.unpack_from(">HHB", blk, o)
    return {"mode": mode, "bg": bgs, "obj_namebase": objname * 2, "obj_nameselect": objsel * 2}


BPP = {0: (2, 2, 2, 2), 1: (4, 4, 2, 0), 2: (4, 4, 0, 0), 3: (8, 4, 0, 0), 4: (8, 2, 0, 0), 5: (4, 2, 0, 0)}


def used_tiles(vram, tilemap, scsize):
    n = 1 if scsize == 0 else (2 if scsize in (1, 2) else 4)
    words = struct.unpack_from("<%dH" % (1024 * n), vram, tilemap)
    return sorted(set(w & 0x3FF for w in words))


def main():
    state = open(sys.argv[1], "rb").read()
    vram = open(sys.argv[2], "rb").read()
    regs = ppu_regs(state)
    print("mode", regs["mode"], "obj base %04X" % regs["obj_namebase"])
    for i, bg in enumerate(regs["bg"]):
        bpp = BPP[regs["mode"]][i]
        if not bpp:
            continue
        tiles = used_tiles(vram, bg["tilemap"], bg["scsize"])
        tb = 8 * bpp
        lo, hi = bg["namebase"] + tiles[0] * tb, bg["namebase"] + tiles[-1] * tb + tb
        print("BG%d %dbpp tilemap %04X base %04X scsize %d: %d tiles used, %03X..%03X (VRAM %04X..%04X)"
              % (i + 1, bpp, bg["tilemap"], bg["namebase"], bg["scsize"], len(tiles), tiles[0], tiles[-1], lo, hi))
        # free runs of >= 32 consecutive unused tile numbers within 0..3FF
        used = set(tiles)
        run = []
        start = None
        for t in range(0x400 + 1):
            if t < 0x400 and t not in used:
                if start is None:
                    start = t
            elif start is not None:
                if t - start >= 32:
                    run.append((start, t - 1))
                start = None
        print("    unused tile runs:", ", ".join("%03X-%03X" % r for r in run))


if __name__ == "__main__":
    main()
