# g560ctl/test/test_new_g815_layout.py
from logitech_lighting.devices.g815.layout import (
    BY_EVDEV, BY_NAME, BY_ZONE, KEYS, PHASE1_VALID_ZONES,
)


def test_zones_are_unique() -> None:
    zones = [k.zone for k in KEYS]
    assert len(zones) == len(set(zones))


def test_positions_are_unique() -> None:
    positions = [(k.x, k.y) for k in KEYS]
    assert len(positions) == len(set(positions))


def test_every_zone_was_valid_on_hardware() -> None:
    assert {k.zone for k in KEYS} <= PHASE1_VALID_ZONES


def test_phase1_zone_map_spot_checks() -> None:
    assert BY_NAME["a"].zone == 0x01
    assert BY_NAME["esc"].zone == 0x26
    assert BY_NAME["space"].zone == 0x29
    assert BY_NAME["f12"].zone == 0x42
    assert BY_NAME["lctrl"].zone == 0x68
    assert BY_NAME["rmeta"].zone == 0x6F
    assert BY_NAME["g1"].zone == 0xB4
    assert BY_NAME["logo"].zone == 0xD2
    assert BY_NAME["backlight"].zone == 0x99


def test_evdev_mapping_covers_main_block() -> None:
    # KEY_A=30, KEY_ESC=1, KEY_SPACE=57, KEY_ENTER=28, KEY_LEFTCTRL=29, KEY_KP0=82
    assert BY_EVDEV[30].name == "a"
    assert BY_EVDEV[1].name == "esc"
    assert BY_EVDEV[57].name == "space"
    assert BY_EVDEV[28].name == "enter"
    assert BY_EVDEV[29].name == "lctrl"
    assert BY_EVDEV[82].name == "kp0"
    letters = [BY_NAME[c] for c in "abcdefghijklmnopqrstuvwxyz"]
    assert all(k.evdev is not None for k in letters)


def test_lookup_tables_agree() -> None:
    for k in KEYS:
        assert BY_ZONE[k.zone] is k and BY_NAME[k.name] is k
        if k.evdev is not None:
            assert BY_EVDEV[k.evdev] is k
