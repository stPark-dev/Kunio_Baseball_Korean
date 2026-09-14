from tools.emu.harness import BUTTONS, PRESS_FRAMES, parse_events, parse_shots


def test_press_is_held_for_a_few_frames():
    script = parse_events(["100:start"], [])
    assert script(99) == 0
    for f in range(100, 100 + PRESS_FRAMES):
        assert script(f) == 1 << BUTTONS["start"]
    assert script(100 + PRESS_FRAMES) == 0


def test_hold_range_is_inclusive_and_combines_with_press():
    script = parse_events(["12:a"], ["10-12:b"])
    assert script(10) == 1 << BUTTONS["b"]
    assert script(12) == (1 << BUTTONS["b"]) | (1 << BUTTONS["a"])
    assert script(13) == 1 << BUTTONS["a"]


def test_parse_shots_keeps_colons_in_path():
    assert parse_shots(["30:out/a:b.png"]) == {30: "out/a:b.png"}
