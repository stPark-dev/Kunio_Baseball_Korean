"""Headless Super Famicom runner built on a libretro core (Snes9x).

Usage:
  python tools/emu/harness.py ROM --frames 600 --shot 300:title.png --shot 600:menu.png \
      --press 200:start --hold 250-260:a --dump-vram vram.bin --dump-ram wram.bin
Buttons: up down left right a b x y l r start select
"""
import argparse
import ctypes as C
import os
import sys

from PIL import Image

ENV_SET_PIXEL_FORMAT = 10
ENV_GET_SYSTEM_DIRECTORY = 9
ENV_GET_SAVE_DIRECTORY = 31
ENV_GET_VARIABLE = 15
ENV_GET_VARIABLE_UPDATE = 17
ENV_GET_CAN_DUPE = 3

# libretro RETRO_DEVICE_ID_JOYPAD_* ids
BUTTONS = {
    "b": 0, "y": 1, "select": 2, "start": 3, "up": 4, "down": 5, "left": 6,
    "right": 7, "a": 8, "x": 9, "l": 10, "r": 11,
}
PRESS_FRAMES = 3


class GameInfo(C.Structure):
    _fields_ = [("path", C.c_char_p), ("data", C.c_void_p),
                ("size", C.c_size_t), ("meta", C.c_char_p)]


class GameGeometry(C.Structure):
    _fields_ = [("base_width", C.c_uint), ("base_height", C.c_uint),
                ("max_width", C.c_uint), ("max_height", C.c_uint),
                ("aspect_ratio", C.c_float)]


class SystemTiming(C.Structure):
    _fields_ = [("fps", C.c_double), ("sample_rate", C.c_double)]


class SystemAvInfo(C.Structure):
    _fields_ = [("geometry", GameGeometry), ("timing", SystemTiming)]


ENV_CB = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO_CB = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AUDIO_BATCH_CB = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
POLL_CB = C.CFUNCTYPE(None)
STATE_CB = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)


class Emulator:
    MEMORY_SAVE_RAM = 0
    MEMORY_SYSTEM_RAM = 2
    MEMORY_VIDEO_RAM = 3

    def __init__(self, core_path, rom_path, sysdir):
        self.core = C.CDLL(core_path)
        self.pixel_format = 0
        self.frame = None
        self.pad = 0
        self.frame_no = 0
        self._sysdir = C.c_char_p(sysdir.encode())
        self._env_cb = ENV_CB(self._environment)
        self._video_cb = VIDEO_CB(self._video)
        self._audio_cb = AUDIO_CB(lambda l, r: None)
        self._audio_batch_cb = AUDIO_BATCH_CB(lambda data, frames: frames)
        self._poll_cb = POLL_CB(lambda: None)
        self._state_cb = STATE_CB(self._input_state)
        core = self.core
        core.retro_set_environment(self._env_cb)
        core.retro_set_video_refresh(self._video_cb)
        core.retro_set_audio_sample(self._audio_cb)
        core.retro_set_audio_sample_batch(self._audio_batch_cb)
        core.retro_set_input_poll(self._poll_cb)
        core.retro_set_input_state(self._state_cb)
        core.retro_init()
        data = open(rom_path, "rb").read()
        self._rom_buf = C.create_string_buffer(data, len(data))
        info = GameInfo(rom_path.encode(), C.cast(self._rom_buf, C.c_void_p),
                        len(data), None)
        core.retro_load_game.restype = C.c_bool
        if not core.retro_load_game(C.byref(info)):
            raise RuntimeError("retro_load_game failed")
        av = SystemAvInfo()
        core.retro_get_system_av_info(C.byref(av))
        self.fps = av.timing.fps

    def _environment(self, cmd, data):
        if cmd == ENV_SET_PIXEL_FORMAT:
            self.pixel_format = C.cast(data, C.POINTER(C.c_int))[0]
            return True
        if cmd in (ENV_GET_SYSTEM_DIRECTORY, ENV_GET_SAVE_DIRECTORY):
            C.cast(data, C.POINTER(C.c_char_p))[0] = self._sysdir
            return True
        if cmd == ENV_GET_CAN_DUPE:
            C.cast(data, C.POINTER(C.c_bool))[0] = True
            return True
        if cmd == ENV_GET_VARIABLE_UPDATE:
            C.cast(data, C.POINTER(C.c_bool))[0] = False
            return True
        return False

    def _video(self, data, width, height, pitch):
        if not data:
            return
        buf = C.string_at(data, pitch * height)
        if self.pixel_format == 1:
            img = Image.frombuffer("RGBX", (width, height), buf, "raw", "BGRX", pitch, 1)
            img = img.convert("RGB")
        elif self.pixel_format == 2:
            img = Image.frombuffer("RGB", (width, height), buf, "raw", "BGR;16", pitch, 1)
        else:
            img = Image.frombuffer("RGB", (width, height), buf, "raw", "BGR;15", pitch, 1)
        self.frame = img.copy()

    def _input_state(self, port, device, index, idx):
        if port != 0:
            return 0
        return 1 if (self.pad >> idx) & 1 else 0

    def memory(self, kind):
        """Copy of a core memory region (system RAM = 128 KB WRAM, video RAM = 64 KB VRAM)."""
        self.core.retro_get_memory_data.restype = C.c_void_p
        self.core.retro_get_memory_size.restype = C.c_size_t
        ptr = self.core.retro_get_memory_data(kind)
        size = self.core.retro_get_memory_size(kind)
        return C.string_at(ptr, size) if ptr and size else b""

    def state(self):
        """Serialized core state (contains CGRAM, OAM and PPU registers)."""
        self.core.retro_serialize_size.restype = C.c_size_t
        size = self.core.retro_serialize_size()
        buf = C.create_string_buffer(size)
        self.core.retro_serialize.restype = C.c_bool
        if not self.core.retro_serialize(buf, size):
            raise RuntimeError("retro_serialize failed")
        return buf.raw

    def run(self, frames, script):
        for _ in range(frames):
            self.pad = script(self.frame_no)
            self.core.retro_run()
            self.frame_no += 1
            yield self.frame_no


def parse_events(presses, holds):
    """Return a script function frame -> button mask.

    presses: ["FRAME:button", ...]  (held for PRESS_FRAMES frames)
    holds:   ["START-END:button", ...] (inclusive range)
    """
    active = {}
    for spec in presses:
        frame, name = spec.split(":")
        for f in range(int(frame), int(frame) + PRESS_FRAMES):
            active[f] = active.get(f, 0) | (1 << BUTTONS[name])
    for spec in holds:
        rng, name = spec.split(":")
        start, end = [int(x) for x in rng.split("-")]
        for f in range(start, end + 1):
            active[f] = active.get(f, 0) | (1 << BUTTONS[name])
    return lambda frame: active.get(frame, 0)


def parse_shots(specs):
    """["FRAME:path", ...] -> {frame: path}"""
    shots = {}
    for spec in specs:
        frame, path = spec.split(":", 1)
        shots[int(frame)] = path
    return shots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--core", default=os.path.join(os.path.dirname(__file__), "snes9x_libretro.so"))
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--shot", action="append", default=[], help="FRAME:file.png")
    ap.add_argument("--press", action="append", default=[], help="FRAME:button")
    ap.add_argument("--hold", action="append", default=[], help="START-END:button")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--dump-ram", help="write WRAM at the last frame to this file")
    ap.add_argument("--dump-vram", help="write VRAM at the last frame to this file")
    ap.add_argument("--dump-state", help="write the serialized core state at the last frame")
    args = ap.parse_args()
    shots = parse_shots(args.shot)
    emu = Emulator(args.core, args.rom, os.path.dirname(os.path.abspath(args.rom)))
    script = parse_events(args.press, args.hold)
    for frame in emu.run(args.frames, script):
        if frame in shots and emu.frame is not None:
            img = emu.frame
            if args.scale > 1:
                img = img.resize((img.width * args.scale, img.height * args.scale), Image.NEAREST)
            img.save(shots[frame])
            print("saved", shots[frame], img.size, file=sys.stderr)
    if args.dump_state:
        data = emu.state()
        open(args.dump_state, "wb").write(data)
        print("dumped", args.dump_state, len(data), "bytes", file=sys.stderr)
    for path, kind in ((args.dump_ram, Emulator.MEMORY_SYSTEM_RAM), (args.dump_vram, Emulator.MEMORY_VIDEO_RAM)):
        if path:
            data = emu.memory(kind)
            open(path, "wb").write(data)
            print("dumped", path, len(data), "bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
