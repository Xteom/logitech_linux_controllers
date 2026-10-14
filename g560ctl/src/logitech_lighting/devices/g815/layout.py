"""G815 key table: name -> HID++ zone, physical center (key units), evdev keycode.

Coordinates are key centers on a US ANSI full-size board, in units of one
letter-key width; y grows downward. The G-key column sits at x = 0.5 and the
main block starts at x = 1.25. Zones follow the Phase 1 map (experiments/README.md):
main block = HID usage - 3, modifiers = usage - 0x78, plus 0x99 / 0x9b-0x9e /
0xb4-0xb8 / 0xd2. Positions of the top-row extras are approximate.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    name: str
    zone: int
    x: float
    y: float
    evdev: int | None


_X0 = 1.25  # left edge of the main block

# (name, HID usage, evdev keycode, center x relative to _X0, row y)
_USAGE_KEYS = [
    # function row (y = 0)
    ("esc", 0x29, 1, 0.5, 0.0),
    ("f1", 0x3A, 59, 2.5, 0.0), ("f2", 0x3B, 60, 3.5, 0.0), ("f3", 0x3C, 61, 4.5, 0.0), ("f4", 0x3D, 62, 5.5, 0.0),
    ("f5", 0x3E, 63, 7.0, 0.0), ("f6", 0x3F, 64, 8.0, 0.0), ("f7", 0x40, 65, 9.0, 0.0), ("f8", 0x41, 66, 10.0, 0.0),
    ("f9", 0x42, 67, 11.5, 0.0), ("f10", 0x43, 68, 12.5, 0.0), ("f11", 0x44, 87, 13.5, 0.0), ("f12", 0x45, 88, 14.5, 0.0),
    ("sysrq", 0x46, 99, 15.75, 0.0), ("scrolllock", 0x47, 70, 16.75, 0.0), ("pause", 0x48, 119, 17.75, 0.0),
    # number row (y = 1.25)
    ("grave", 0x35, 41, 0.5, 1.25),
    ("1", 0x1E, 2, 1.5, 1.25), ("2", 0x1F, 3, 2.5, 1.25), ("3", 0x20, 4, 3.5, 1.25), ("4", 0x21, 5, 4.5, 1.25),
    ("5", 0x22, 6, 5.5, 1.25), ("6", 0x23, 7, 6.5, 1.25), ("7", 0x24, 8, 7.5, 1.25), ("8", 0x25, 9, 8.5, 1.25),
    ("9", 0x26, 10, 9.5, 1.25), ("0", 0x27, 11, 10.5, 1.25), ("minus", 0x2D, 12, 11.5, 1.25), ("equal", 0x2E, 13, 12.5, 1.25),
    ("backspace", 0x2A, 14, 14.0, 1.25),
    ("insert", 0x49, 110, 15.75, 1.25), ("home", 0x4A, 102, 16.75, 1.25), ("pageup", 0x4B, 104, 17.75, 1.25),
    ("numlock", 0x53, 69, 19.0, 1.25), ("kpslash", 0x54, 98, 20.0, 1.25), ("kpasterisk", 0x55, 55, 21.0, 1.25), ("kpminus", 0x56, 74, 22.0, 1.25),
    # top letter row (y = 2.25)
    ("tab", 0x2B, 15, 0.75, 2.25),
    ("q", 0x14, 16, 2.0, 2.25), ("w", 0x1A, 17, 3.0, 2.25), ("e", 0x08, 18, 4.0, 2.25), ("r", 0x15, 19, 5.0, 2.25),
    ("t", 0x17, 20, 6.0, 2.25), ("y", 0x1C, 21, 7.0, 2.25), ("u", 0x18, 22, 8.0, 2.25), ("i", 0x0C, 23, 9.0, 2.25),
    ("o", 0x12, 24, 10.0, 2.25), ("p", 0x13, 25, 11.0, 2.25), ("leftbrace", 0x2F, 26, 12.0, 2.25), ("rightbrace", 0x30, 27, 13.0, 2.25),
    ("backslash", 0x31, 43, 14.25, 2.25),
    ("delete", 0x4C, 111, 15.75, 2.25), ("end", 0x4D, 107, 16.75, 2.25), ("pagedown", 0x4E, 109, 17.75, 2.25),
    ("kp7", 0x5F, 71, 19.0, 2.25), ("kp8", 0x60, 72, 20.0, 2.25), ("kp9", 0x61, 73, 21.0, 2.25), ("kpplus", 0x57, 78, 22.0, 2.75),
    # home row (y = 3.25)
    ("capslock", 0x39, 58, 0.875, 3.25),
    ("a", 0x04, 30, 2.25, 3.25), ("s", 0x16, 31, 3.25, 3.25), ("d", 0x07, 32, 4.25, 3.25), ("f", 0x09, 33, 5.25, 3.25),
    ("g", 0x0A, 34, 6.25, 3.25), ("h", 0x0B, 35, 7.25, 3.25), ("j", 0x0D, 36, 8.25, 3.25), ("k", 0x0E, 37, 9.25, 3.25),
    ("l", 0x0F, 38, 10.25, 3.25), ("semicolon", 0x33, 39, 11.25, 3.25), ("apostrophe", 0x34, 40, 12.25, 3.25),
    ("enter", 0x28, 28, 13.875, 3.25),
    ("kp4", 0x5C, 75, 19.0, 3.25), ("kp5", 0x5D, 76, 20.0, 3.25), ("kp6", 0x5E, 77, 21.0, 3.25),
    # bottom letter row (y = 4.25)
    ("z", 0x1D, 44, 2.75, 4.25), ("x", 0x1B, 45, 3.75, 4.25), ("c", 0x06, 46, 4.75, 4.25), ("v", 0x19, 47, 5.75, 4.25),
    ("b", 0x05, 48, 6.75, 4.25), ("n", 0x11, 49, 7.75, 4.25), ("m", 0x10, 50, 8.75, 4.25), ("comma", 0x36, 51, 9.75, 4.25),
    ("dot", 0x37, 52, 10.75, 4.25), ("slash", 0x38, 53, 11.75, 4.25),
    ("up", 0x52, 103, 16.75, 4.25),
    ("kp1", 0x59, 79, 19.0, 4.25), ("kp2", 0x5A, 80, 20.0, 4.25), ("kp3", 0x5B, 81, 21.0, 4.25), ("kpenter", 0x58, 96, 22.0, 4.75),
    # space row (y = 5.25)
    ("space", 0x2C, 57, 6.875, 5.25), ("compose", 0x65, 127, 13.125, 5.25),
    ("left", 0x50, 105, 15.75, 5.25), ("down", 0x51, 108, 16.75, 5.25), ("right", 0x4F, 106, 17.75, 5.25),
    ("kp0", 0x62, 82, 19.5, 5.25), ("kpdot", 0x63, 83, 21.0, 5.25),
]

# Modifiers: zone = HID usage (0xE0-0xE7) - 0x78. rmeta sits where the G815 has Fn.
_MODIFIER_KEYS = [
    ("lctrl", 0xE0, 29, 0.625, 5.25), ("lshift", 0xE1, 42, 1.125, 4.25), ("lalt", 0xE2, 56, 3.125, 5.25),
    ("lmeta", 0xE3, 125, 1.875, 5.25), ("rctrl", 0xE4, 97, 14.375, 5.25), ("rshift", 0xE5, 54, 13.625, 4.25),
    ("ralt", 0xE6, 100, 10.625, 5.25), ("rmeta", 0xE7, 126, 11.875, 5.25),
]

# Extras: (name, zone, evdev or None, absolute x, y). Media order is confirmed in Gate A.
_EXTRA_KEYS = [
    ("g1", 0xB4, None, 0.5, 1.25), ("g2", 0xB5, None, 0.5, 2.25), ("g3", 0xB6, None, 0.5, 3.25),
    ("g4", 0xB7, None, 0.5, 4.25), ("g5", 0xB8, None, 0.5, 5.25),
    ("logo", 0xD2, None, 0.5, 0.0),
    ("backlight", 0x99, None, _X0 + 8.0, -1.0),   # above F6 (user-confirmed)
    ("media_play", 0x9B, 164, _X0 + 19.0, -1.0), ("media_mute", 0x9C, 113, _X0 + 20.0, -1.0),
    ("media_next", 0x9D, 163, _X0 + 21.0, -1.0), ("media_prev", 0x9E, 165, _X0 + 22.0, -1.0),
]


def _build() -> tuple[Key, ...]:
    keys = [Key(n, usage - 3, _X0 + x, y, ev) for n, usage, ev, x, y in _USAGE_KEYS]
    keys += [Key(n, usage - 0x78, _X0 + x, y, ev) for n, usage, ev, x, y in _MODIFIER_KEYS]
    keys += [Key(n, zone, x, y, ev) for n, zone, ev, x, y in _EXTRA_KEYS]
    return tuple(keys)


KEYS: tuple[Key, ...] = _build()
BY_ZONE: dict[int, Key] = {k.zone: k for k in KEYS}
BY_NAME: dict[str, Key] = {k.name: k for k in KEYS}
BY_EVDEV: dict[int, Key] = {k.evdev: k for k in KEYS if k.evdev is not None}

# Zones the G815 accepted one at a time in Phase 1 (experiments/README.md, rung C).
PHASE1_VALID_ZONES: frozenset[int] = frozenset(
    list(range(0x01, 0x70)) + [0x99, 0x9B, 0x9C, 0x9D, 0x9E, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xD2]
)
