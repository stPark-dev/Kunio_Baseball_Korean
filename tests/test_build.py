import struct

from tools.kbb import build


def test_jml_encoding():
    assert build.jml(0xB18004) == bytes([0x5C, 0x04, 0x80, 0xB1])


def test_apply_patches_checks_original_bytes():
    rom = bytearray(b"\x00" * 16)
    build.apply_patches(rom, [(4, b"\x00\x00", b"\x12\x34")])
    assert rom[4:6] == b"\x12\x34"
    try:
        build.apply_patches(rom, [(4, b"\x00\x00", b"\x56\x78")])
    except build.BuildError:
        pass
    else:
        raise AssertionError("mismatching original bytes must be rejected")


def test_fix_checksum_is_consistent():
    rom = bytearray(range(256)) * (0x8000 // 256)
    build.fix_checksum(rom)
    comp, chk = struct.unpack_from("<HH", rom, build.HEADER_COMPLEMENT)
    assert comp ^ chk == 0xFFFF
    assert build.checksum(rom) == chk


def test_patch_table_addresses_use_table_map():
    p = build.patches({"story": 0x9A22, "surname": 0x8018, "name_extra2": 0x87D5, "item": 0x8A27, "school": 0x99A2})
    # with the original addresses the data patches are no-ops apart from the bank byte
    changed = [off for off, old, new in p if old != new]
    assert 0x0869FA in changed and 0x086A05 not in changed


def test_label_table_and_marking():
    from tools.kbb import encode
    rows = [{"id": "a", "bank": "11", "top": "8003", "bottom": "800B", "n": "4", "korean": "가 나"}]
    gs = encode.GlyphSet(["가 나"])
    data = build.label_table(rows, gs)
    assert data[:2] == struct.pack("<H", 0xC002)
    assert data[2:] == gs.encode("가 나")
    rom = bytearray(0x90000)
    build.mark_labels(rom, rows)
    top = 0x11 * 0x8000 + 3
    assert struct.unpack_from("<H", rom, top)[0] == 0xC000
    assert struct.unpack_from("<H", rom, top + 8)[0] == 0xD000
    assert rom[top + 2:top + 8] == b"\x00" * 6
