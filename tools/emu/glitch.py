"""Find one-frame graphic glitches.

A frame that differs from *both* its neighbours while the neighbours agree with each other is a
transient tear; an ordinary scene change is not, because the frames after it stay changed. The
one this catches is the jolt when a line of dialogue turns over (see README, 남은 문제).

  python tools/emu/glitch.py build/Kunio_Baseball_Korean.sfc --from 6400 --to 15000
  python tools/emu/glitch.py build/original.sfc --from 6400 --to 15000     # the control: 0

Every candidate is saved as a three-frame strip so the artefact can be seen, not just counted.
The comparison against the original ROM is the whole point: run both, and only the difference
between the two counts says anything about the patch.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.emu.harness import BUTTONS, Emulator

PRESS_HOLD = 3
JUMP = 200          # x100 mean channel difference that counts as "the frame changed"


def script(advance, until):
    """frame -> button mask: boot into the story and press A every `advance` frames."""
    events = {}

    def press(frame, name):
        for f in range(frame, frame + PRESS_HOLD):
            events[f] = events.get(f, 0) | (1 << BUTTONS[name])

    press(4900, "start")
    for f in range(5650, 6200, 100):
        press(f, "a")
    for f in range(6250, until + 100, advance):
        press(f, "a")
    return lambda frame: events.get(frame, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--core", default=os.path.join(os.path.dirname(__file__), "snes9x_libretro.so"))
    ap.add_argument("--from", dest="first", type=int, default=6400)
    ap.add_argument("--to", dest="last", type=int, default=15000)
    ap.add_argument("--advance", type=int, default=40, help="frames between A presses")
    ap.add_argument("--save", type=int, default=6, help="strips to write out")
    ap.add_argument("--out", default="build/glitch")
    args = ap.parse_args()

    emu = Emulator(args.core, args.rom, os.path.dirname(os.path.abspath(args.rom)))
    frames = {}
    for n in emu.run(args.last, script(args.advance, args.last)):
        if args.first <= n <= args.last and emu.frame is not None:
            frames[n] = np.asarray(emu.frame.convert("RGB"), dtype=np.int16)

    def diff(a, b):
        return int(np.abs(frames[a] - frames[b]).mean() * 100)

    order = sorted(frames)
    found = []
    for i in range(1, len(order) - 1):
        prev, here, nxt = order[i - 1], order[i], order[i + 1]
        before, after, across = diff(prev, here), diff(here, nxt), diff(prev, nxt)
        if before > JUMP and after > JUMP and across < min(before, after) // 2:
            found.append((before + after - 2 * across, here))
    print("frames %d-%d: %d transient frame(s)" % (order[0], order[-1], len(found)))

    found.sort(reverse=True)
    if found and args.save:
        os.makedirs(args.out, exist_ok=True)
    for score, here in found[:args.save]:
        print("  f%d: score %d" % (here, score))
        strip = Image.new("RGB", (256 * 2 * 3 + 16, 224 * 2 + 16), (20, 20, 20))
        draw = ImageDraw.Draw(strip)
        for i, f in enumerate((here - 1, here, here + 1)):
            if f in frames:
                strip.paste(Image.fromarray(frames[f].astype("uint8")).resize((512, 448),
                                                                              Image.NEAREST),
                            (i * 520, 14))
                draw.text((i * 520 + 4, 2), "f%d" % f, fill=(255, 220, 90))
        strip.save(os.path.join(args.out, "glitch_%d.png" % here))


if __name__ == "__main__":
    main()
