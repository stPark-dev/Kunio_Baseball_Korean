"""Long seeded play-through with a freeze detector and the renderer's drop counters.

`harness.py` only shoots frames you name in advance, which is no use for "does it survive an
hour of play". This drives the ROM from a cold boot with a seeded stream of button presses and
watches two things every frame:

- the framebuffer and WRAM together. A real freeze is a long run where *both* are identical;
  fades, pauses and held scenes always move one or the other, so the rule gives no false hits.
- the in-game commentary counters in `asm/text.s` (`G_QFULL`, `G_PLOST`, `G_RLOST`). Cells the
  VRAM queue turned away should all come back from the parked-cell ring, so `lost` must stay 0.

  python tools/emu/playtest.py build/Kunio_Baseball_Korean.sfc --frames 200000 --seed 3
  python tools/emu/playtest.py ROM --mode quick --frames 45000   # one-inning practice match
"""
import argparse
import hashlib
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.emu.harness import BUTTONS, Emulator

PRESS_HOLD = 3
STALL_FRAMES = 120                      # two seconds of a wholly unchanged machine
# WRAM offsets of the counters (GST = $7E:14E0, G_PEND ring at $7E:9B0A)
COUNTERS = {"parked": 0x14F0, "ring_lost": 0x14F2, "lost": 0x9B1E}
MASH = ["a"] * 8 + ["b", "up", "down", "left", "right", "x", "y"]


def script(mode, seed, frames):
    """frame -> button mask: boot into `mode`, then mash until `frames`."""
    events = {}

    def press(frame, name, hold=PRESS_HOLD):
        for f in range(frame, frame + hold):
            events[f] = events.get(f, 0) | (1 << BUTTONS[name])

    press(4900, "start")                                # title -> main menu
    if mode == "story":
        for f in range(5650, 6200, 100):                # confirm every row down to OK
            press(f, "a")
        start = 6250
    else:                                               # a one-inning practice match
        press(5650, "right")                            # mode -> 연습 시합
        press(5750, "a")
        press(5850, "a")
        f = 5950
        for _ in range(8):                              # innings 09 -> 01
            press(f, "left")
            f += 40
        for f in (6350, 6450, 6550, 6650, 6750, 6850, 7100, 7400, 7700, 8000):
            press(f, "a")                               # rest of the setup, then the team grid
        start = 8300
    rnd = random.Random(seed)
    f = start
    while f < frames:
        for k in range(f, f + PRESS_HOLD):
            events[k] = events.get(k, 0) | (1 << BUTTONS[rnd.choice(MASH)])
        f += rnd.randint(20, 45)
    return lambda frame: events.get(frame, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--core", default=os.path.join(os.path.dirname(__file__), "snes9x_libretro.so"))
    ap.add_argument("--mode", choices=("story", "quick"), default="story")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--frames", type=int, default=120000)
    ap.add_argument("--shot-every", type=int, default=0, help="save a frame every N frames")
    ap.add_argument("--out", default="build/playtest", help="directory for the frames")
    args = ap.parse_args()

    emu = Emulator(args.core, args.rom, os.path.dirname(os.path.abspath(args.rom)))
    if args.shot_every:
        os.makedirs(args.out, exist_ok=True)
    digest = lambda b: hashlib.blake2b(b, digest_size=8).digest()

    was = None
    run_start = run_len = 0
    stalls = []
    for n in emu.run(args.frames, script(args.mode, args.seed, args.frames)):
        if args.shot_every and n % args.shot_every == 0 and emu.frame is not None:
            emu.frame.save(os.path.join(args.out, "%07d.png" % n))
        now = (digest(emu.frame.tobytes()) if emu.frame else b"",
               digest(emu.memory(Emulator.MEMORY_SYSTEM_RAM)))
        if now == was:
            if not run_len:
                run_start = n
            run_len += 1
        else:
            if run_len >= STALL_FRAMES:
                stalls.append((run_start, run_len))
            run_len = 0
        was = now
    if run_len >= STALL_FRAMES:
        stalls.append((run_start, run_len))

    print("ran %d frames, mode %s, seed %d" % (args.frames, args.mode, args.seed))
    if stalls:
        print("%d stall(s) of >= %d identical frames:" % (len(stalls), STALL_FRAMES))
        for start, length in sorted(stalls, key=lambda s: -s[1])[:10]:
            print("  frame %d..%d (%.1fs)" % (start, start + length, length / 60))
    else:
        print("no stall >= %d frames of identical video and WRAM" % STALL_FRAMES)
    ram = emu.memory(Emulator.MEMORY_SYSTEM_RAM)
    print("commentary cells: " + "  ".join(
        "%s=%d" % (name, ram[off] | (ram[off + 1] << 8)) for name, off in COUNTERS.items()))


if __name__ == "__main__":
    main()
