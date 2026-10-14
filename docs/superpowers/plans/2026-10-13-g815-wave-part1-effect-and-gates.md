# G815 Wave — Part 1: Effect Core and Feasibility Gates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure effect modules (`layout`, `presets`, `ripple`, `frame`) and run the spec's two hardware feasibility gates:
- **Gate A:** claim sequence and committed fps.
- **Gate B:** XI2 raw keypress input.

The gate results are recorded in the spec, so Part 2 (transport, daemon, CLI, service) can be planned from verified facts.

**Architecture:** The new subpackage `logitech_lighting/devices/g815/` holds pure, hardware-free modules, tested with pytest. Two throwaway probes in `experiments/` reuse those modules against the real keyboard and the real X server. Nothing in the live CLI or the G560 path changes in Part 1.

**Tech Stack:** Python 3.10 (`g560ctl/.venv`), pytest, `hidapi` 0.15 (`import hidraw`), `python-xlib` ≥ 0.29.

**Spec:** `docs/superpowers/specs/2026-10-13-g815-wave-design.md`

**Why two plans:** Part 2's code depends on bytes and behaviours that only Gate A can confirm:
- SetSWControl;
- fn 1/fn 5 echo;
- zone discovery;
- the ping echo;
- whether `0x4522` is needed.

Its keypress code depends on Gate B. Writing Part 2 now would mean writing placeholders. The spec mandates this order ("Build order and gates").

## Global Constraints

- **Device:** G815 `046d:c33f`. The HID++ node is the hidapi `hidraw` entry with usage page `0xFF43`, usage `0x0602`. Only 20-byte long reports (`0x11`, device `0xFF`).
- **Never `import hid`.** It is hidapi's libusb backend and would detach the keyboard driver. Always use `import hidraw`.
- **Base color** `#140028`.
- **Presets:**
  - `red`: `#ffffff` → `#ff2a2a` → `#b0005a` → base.
  - `blue`: `#ffffff` → `#33ccff` → `#1f4fff` → base.
- **Effect constants:**
  - speed 25 units/s;
  - band 3 units;
  - lifetime 1.2 s;
  - origin flash 80 ms;
  - max 8 rings;
  - `u` quantized to 8 steps and intensity to 16 steps (palette ≤ 129 colors);
  - overlap takes the max intensity.
- **Zone map (Phase 1, confirmed on hardware):**
  - main block = HID usage − 3 (`0x01-0x67`);
  - modifiers `0x68-0x6f`;
  - `0x99` backlight key;
  - media `0x9b-0x9e`;
  - G1-G5 `0xb4-0xb8`;
  - logo `0xd2`.
- **HID++ functions on `0x8081`:**
  - fn 1 setIndividualRgbZones `[zone,r,g,b]×≤4`;
  - fn 5 setRangeRgbZones `[start,end,r,g,b]×≤3`;
  - fn 6 setRgbZonesSingleValue `[r,g,b, zone×13]`; a short packet is padded by repeating one of its own zones;
  - fn 7 frameEnd `[00]`.
- **Claim candidate** (source: Solaar `rgb_power.py`):
  - `0x8100` fn 1 `[02]`;
  - `0x8071` fn 5 SetSWControl `[01,03,04]` (SW_ACTIVE).
- **Release:**
  - `0x8071` fn 5 `[01,00,00]`;
  - `0x8100` fn 1 `[01]`.
- **Zone discovery** (source: OpenRGB `DiscoverPerKeyZones`):
  - `0x8081` fn 0 with params `[00, page, 00]`, for pages 0-2;
  - the reply params bytes 2..15 are a 14-byte bitmap, LSB-first, with `zone = page*112 + byte*8 + bit`.
- **Ping:** root (index 0) fn 1 getProtocolVersion `[00,00,ping]`. The reply echoes `ping` at params byte 2.
- **Tests:** `g560ctl/test/test_new_g815_*.py`. The suite command is `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`. The existing 27 tests must stay green.
- **Out of scope for Part 1:**
  - no `cli.py` change;
  - no `pyproject.toml` dependency changes, except adding `python-xlib` in Task 6;
  - no G560 changes.

## Review Focus

1. **A press on a key absent from the layout** (e.g. a G-key that X11 maps to nothing, or an unmapped keycode) must be ignored, not crash `ripple.press`. *(Task 3 test `test_press_unknown_key_is_ignored`.)*
2. **A frame whose changed zones include zones the keyboard doesn't report** must never emit them, even inside fn 6 padding or fn 5 ranges spanning a gap. *(Task 4 test `test_range_never_spans_invalid_zone`.)*
3. **Many keys sharing one color across a big frame** (e.g. the first full repaint, all base) must stay within 16 parameter bytes per packet and cover every zone exactly once. *(Task 4 test `test_full_repaint_covers_every_valid_zone_once`.)*
4. **Presses arriving faster than rings expire** (a key held down auto-repeating, or a fast burst) must cap at 8 rings and keep the newest. *(Task 3 test `test_ring_cap_keeps_newest`.)*
5. **Preset switching mid-animation** must recolor live rings on the next render without crashing or leaving stale colors. *(Task 3 test `test_set_preset_recolors_live_rings`.)*

---

### Task 1: Subpackage scaffold and `layout.py`

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/__init__.py`
- Create: `g560ctl/src/logitech_lighting/devices/g815/layout.py`
- Test: `g560ctl/test/test_new_g815_layout.py`

**Interfaces:**
- Produces:
  - `Key` (frozen dataclass): `name: str`, `zone: int`, `x: float`, `y: float`, `evdev: int | None`
  - `KEYS: tuple[Key, ...]`
  - `BY_ZONE: dict[int, Key]`
  - `BY_NAME: dict[str, Key]`
  - `BY_EVDEV: dict[int, Key]`
  - `PHASE1_VALID_ZONES: frozenset[int]`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_layout.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'logitech_lighting.devices.g815'`

- [ ] **Step 3: Write the implementation**

`g560ctl/src/logitech_lighting/devices/g815/__init__.py`:

```python
"""Logitech G815 per-key lighting (wave effect). See docs/superpowers/specs/2026-10-13-g815-wave-design.md."""
```

`g560ctl/src/logitech_lighting/devices/g815/layout.py`:

```python
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
    ("backlight", 0x99, None, _X0 + 15.75, -1.0),
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
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_layout.py -q`
Expected: `6 passed`

- [ ] **Step 5: Run the full suite**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `33 passed`

- [ ] **Step 6: Commit**

```bash
git add g560ctl/src/logitech_lighting/devices/g815/__init__.py g560ctl/src/logitech_lighting/devices/g815/layout.py g560ctl/test/test_new_g815_layout.py
git commit -m "feat(g815): key layout with zones, positions and evdev codes"
```

---

### Task 2: `presets.py` (colors, gradients, quantization)

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/presets.py`
- Test: `g560ctl/test/test_new_g815_presets.py`

**Interfaces:**
- Produces:
  - `Color = tuple[int, int, int]`
  - `BASE: Color = (0x14, 0x00, 0x28)`
  - `Preset` (frozen dataclass): `name: str`, `stops: tuple[Color, ...]`
  - `PRESETS: dict[str, Preset]` (keys `"red"`, `"blue"`)
  - `U_STEPS = 8`, `INTENSITY_STEPS = 16`
  - `lerp(a: Color, b: Color, t: float) -> Color`
  - `gradient(stops: tuple[Color, ...], u: float) -> Color`
  - `quantize(value: float, steps: int) -> float`
  - `ring_color(preset: Preset, u: float, intensity: float) -> Color` (quantizes both inputs; the gradient tail is `BASE`)

- [ ] **Step 1: Write the failing tests**

```python
# g560ctl/test/test_new_g815_presets.py
from logitech_lighting.devices.g815.presets import (
    BASE, INTENSITY_STEPS, PRESETS, U_STEPS, gradient, lerp, quantize, ring_color,
)


def test_base_and_preset_stops() -> None:
    assert BASE == (0x14, 0x00, 0x28)
    assert PRESETS["red"].stops == ((255, 255, 255), (0xFF, 0x2A, 0x2A), (0xB0, 0x00, 0x5A))
    assert PRESETS["blue"].stops == ((255, 255, 255), (0x33, 0xCC, 0xFF), (0x1F, 0x4F, 0xFF))


def test_lerp_endpoints_and_midpoint() -> None:
    assert lerp((0, 0, 0), (200, 100, 50), 0.0) == (0, 0, 0)
    assert lerp((0, 0, 0), (200, 100, 50), 1.0) == (200, 100, 50)
    assert lerp((0, 0, 0), (200, 100, 50), 0.5) == (100, 50, 25)


def test_gradient_hits_stops_evenly() -> None:
    stops = ((0, 0, 0), (100, 100, 100), (200, 200, 200))
    assert gradient(stops, 0.0) == (0, 0, 0)
    assert gradient(stops, 0.5) == (100, 100, 100)
    assert gradient(stops, 1.0) == (200, 200, 200)
    assert gradient(stops, 0.25) == (50, 50, 50)


def test_quantize_steps() -> None:
    assert quantize(0.0, 16) == 0.0 and quantize(1.0, 16) == 1.0
    assert quantize(0.30, 8) == quantize(0.33, 8)   # same step (x7 -> 2.1, 2.31)
    assert len({quantize(i / 1000, 8) for i in range(1001)}) == 8


def test_ring_color_edges() -> None:
    red = PRESETS["red"]
    assert ring_color(red, 0.0, 1.0) == (255, 255, 255)   # leading edge, full intensity
    assert ring_color(red, 1.0, 1.0) == BASE              # tail fades into base
    assert ring_color(red, 0.3, 0.0) == BASE              # zero intensity is base


def test_palette_is_bounded() -> None:
    for preset in PRESETS.values():
        colors = {ring_color(preset, u / 200, i / 200) for u in range(201) for i in range(201)}
        assert len(colors) <= U_STEPS * INTENSITY_STEPS + 1
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_presets.py -q`
Expected: FAIL with `ModuleNotFoundError: ... presets`

- [ ] **Step 3: Write the implementation**

```python
# g560ctl/src/logitech_lighting/devices/g815/presets.py
"""Wave colors: base, the two presets, gradient interpolation and quantization."""
from __future__ import annotations

from dataclasses import dataclass

Color = tuple[int, int, int]

BASE: Color = (0x14, 0x00, 0x28)
U_STEPS = 8
INTENSITY_STEPS = 16


@dataclass(frozen=True)
class Preset:
    name: str
    stops: tuple[Color, ...]  # leading edge -> tail; BASE is appended as the last stop


PRESETS: dict[str, Preset] = {
    "red": Preset("red", ((0xFF, 0xFF, 0xFF), (0xFF, 0x2A, 0x2A), (0xB0, 0x00, 0x5A))),
    "blue": Preset("blue", ((0xFF, 0xFF, 0xFF), (0x33, 0xCC, 0xFF), (0x1F, 0x4F, 0xFF))),
}


def lerp(a: Color, b: Color, t: float) -> Color:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def gradient(stops: tuple[Color, ...], u: float) -> Color:
    """Evenly spaced stops over u in [0, 1]."""
    u = min(max(u, 0.0), 1.0)
    span = len(stops) - 1
    pos = u * span
    i = min(int(pos), span - 1)
    return lerp(stops[i], stops[i + 1], pos - i)


def quantize(value: float, steps: int) -> float:
    value = min(max(value, 0.0), 1.0)
    return round(value * (steps - 1)) / (steps - 1)


def ring_color(preset: Preset, u: float, intensity: float) -> Color:
    band = gradient(preset.stops + (BASE,), quantize(u, U_STEPS))
    return lerp(BASE, band, quantize(intensity, INTENSITY_STEPS))
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_presets.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add g560ctl/src/logitech_lighting/devices/g815/presets.py g560ctl/test/test_new_g815_presets.py
git commit -m "feat(g815): wave presets, gradients and quantization"
```

---

### Task 3: `ripple.py` (the effect)

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/ripple.py`
- Test: `g560ctl/test/test_new_g815_ripple.py`

**Interfaces:**
- Consumes: `Key`, `KEYS`, `BY_NAME` (Task 1); `Color`, `BASE`, `Preset`, `PRESETS`, `ring_color`, `quantize`, `INTENSITY_STEPS` (Task 2)
- Produces:
  - constants `SPEED = 25.0`, `BAND = 3.0`, `LIFETIME = 1.2`, `FLASH = 0.08`, `MAX_RINGS = 8`
  - `Ripple(keys: tuple[Key, ...] = KEYS, preset: Preset = PRESETS["red"])` with:
    - `press(name: str, t: float) -> None` (unknown names and presses while paused are ignored);
    - `pause()` / `resume()` and the `paused: bool` property;
    - `clear() -> None`;
    - `set_preset(preset: Preset) -> None`;
    - `active: bool` property (any live ring);
    - `render(t: float) -> dict[int, Color]` (every zone in `keys`).

- [ ] **Step 1: Write the failing tests**

```python
# g560ctl/test/test_new_g815_ripple.py
import math

from logitech_lighting.devices.g815.layout import BY_NAME, KEYS
from logitech_lighting.devices.g815.presets import BASE, PRESETS, ring_color
from logitech_lighting.devices.g815.ripple import BAND, FLASH, LIFETIME, MAX_RINGS, SPEED, Ripple


def _dist(a: str, b: str) -> float:
    ka, kb = BY_NAME[a], BY_NAME[b]
    return math.hypot(ka.x - kb.x, ka.y - kb.y)


def test_idle_frame_is_all_base() -> None:
    frame = Ripple().render(0.0)
    assert set(frame) == {k.zone for k in KEYS}
    assert set(frame.values()) == {BASE}


def test_origin_flash() -> None:
    r = Ripple()
    r.press("g", 10.0)
    assert r.render(10.0 + FLASH / 2)[BY_NAME["g"].zone] == PRESETS["red"].stops[0]


def test_band_color_at_known_distance() -> None:
    r = Ripple()
    r.press("g", 0.0)
    d = _dist("g", "j")
    t = (d + 0.5 * BAND) / SPEED          # j sits mid-band
    expected = ring_color(PRESETS["red"], 0.5, 1.0 - t / LIFETIME)
    assert r.render(t)[BY_NAME["j"].zone] == expected


def test_key_outside_band_is_base() -> None:
    r = Ripple()
    r.press("g", 0.0)
    far = _dist("g", "kpenter")
    assert r.render(0.5 * far / SPEED)[BY_NAME["kpenter"].zone] == BASE


def test_ring_expires() -> None:
    r = Ripple()
    r.press("g", 0.0)
    assert r.active
    assert set(r.render(LIFETIME + 0.01).values()) == {BASE}
    assert not r.active


def test_ring_cap_keeps_newest() -> None:
    r = Ripple()
    names = ["a", "s", "d", "f", "g", "h", "j", "k", "l"]          # 9 presses
    for i, n in enumerate(names):
        r.press(n, i * 0.001)
    t = len(names) * 0.001
    frame = r.render(t + FLASH / 4)
    assert frame[BY_NAME["l"].zone] == PRESETS["red"].stops[0]   # newest kept
    assert len(r._rings) == MAX_RINGS                             # oldest ("a") dropped
    assert r._rings[0].zone == BY_NAME["s"].zone


def test_overlap_takes_max_intensity() -> None:
    r = Ripple()
    r.press("a", 0.0)
    r.press("l", 0.6)
    t = 0.6 + FLASH / 2
    assert r.render(t)[BY_NAME["l"].zone] == PRESETS["red"].stops[0]  # young ring wins


def test_pause_ignores_presses_and_clear_resets() -> None:
    r = Ripple()
    r.pause()
    r.press("g", 0.0)
    assert not r.active
    r.resume()
    r.press("g", 0.0)
    assert r.active
    r.clear()
    assert not r.active and set(r.render(0.01).values()) == {BASE}


def test_press_unknown_key_is_ignored() -> None:
    r = Ripple()
    r.press("no-such-key", 0.0)
    assert not r.active


def test_set_preset_recolors_live_rings() -> None:
    r = Ripple()
    r.press("g", 0.0)
    r.set_preset(PRESETS["blue"])
    d = _dist("g", "j")
    t = (d + 0.5 * BAND) / SPEED
    assert r.render(t)[BY_NAME["j"].zone] == ring_color(PRESETS["blue"], 0.5, 1.0 - t / LIFETIME)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_ripple.py -q`
Expected: FAIL with `ModuleNotFoundError: ... ripple`

- [ ] **Step 3: Write the implementation**

```python
# g560ctl/src/logitech_lighting/devices/g815/ripple.py
"""Ripple effect: pure function of (presses, time) -> color per zone."""
from __future__ import annotations

import math
from dataclasses import dataclass

from logitech_lighting.devices.g815.layout import KEYS, Key
from logitech_lighting.devices.g815.presets import (
    BASE, INTENSITY_STEPS, PRESETS, Color, Preset, quantize, ring_color,
)

SPEED = 25.0      # key units per second
BAND = 3.0        # ring band width, key units
LIFETIME = 1.2    # seconds
FLASH = 0.08      # origin flash, seconds
MAX_RINGS = 8


@dataclass(frozen=True)
class Ring:
    zone: int
    x: float
    y: float
    t0: float


class Ripple:
    def __init__(self, keys: tuple[Key, ...] = KEYS, preset: Preset = PRESETS["red"]) -> None:
        self._keys = keys
        self._by_name = {k.name: k for k in keys}
        self._preset = preset
        self._rings: list[Ring] = []
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def active(self) -> bool:
        return bool(self._rings)

    def set_preset(self, preset: Preset) -> None:
        self._preset = preset

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def clear(self) -> None:
        self._rings.clear()

    def press(self, name: str, t: float) -> None:
        key = self._by_name.get(name)
        if key is None or self._paused:
            return
        self._rings.append(Ring(key.zone, key.x, key.y, t))
        del self._rings[:-MAX_RINGS]

    def render(self, t: float) -> dict[int, Color]:
        self._rings = [r for r in self._rings if t - r.t0 < LIFETIME]
        frame: dict[int, Color] = {}
        flash = self._preset.stops[0]
        for key in self._keys:
            best_i = 0.0
            color = BASE
            for ring in self._rings:
                age = t - ring.t0
                if key.zone == ring.zone and age < FLASH:
                    best_i, color = 1.0 + 1e-9, flash   # the flash beats any band
                    continue
                d = math.hypot(key.x - ring.x, key.y - ring.y)
                u = (SPEED * age - d) / BAND
                if 0.0 <= u <= 1.0:
                    intensity = quantize(1.0 - age / LIFETIME, INTENSITY_STEPS)
                    if intensity > best_i:
                        best_i, color = intensity, ring_color(self._preset, u, intensity)
            frame[key.zone] = color
        return frame
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_ripple.py -q`
Expected: `10 passed`

If `test_band_color_at_known_distance` fails by one quantization step, compare the expected value against `ring_color(..., 1.0 - t/LIFETIME)`. `ring_color` quantizes its own inputs, so both sides must go through it. Fix the code, not the test.

- [ ] **Step 5: Commit**

```bash
git add g560ctl/src/logitech_lighting/devices/g815/ripple.py g560ctl/test/test_new_g815_ripple.py
git commit -m "feat(g815): ripple effect as a pure render function"
```

---

### Task 4: `frame.py` (minimal packet encoder)

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/frame.py`
- Test: `g560ctl/test/test_new_g815_frame.py`

**Interfaces:**
- Consumes: `Color` (Task 2)
- Produces:
  - constants `FN_SET_INDIVIDUAL = 1`, `FN_SET_RANGE = 5`, `FN_SET_SINGLE = 6`, `FN_FRAME_END = 7`
  - `Write = tuple[int, bytes]`, meaning (function, params ≤ 16 bytes); the transport adds the HID++ header
  - `encode(prev: dict[int, Color] | None, nxt: dict[int, Color], valid: frozenset[int], resync: tuple[int, ...] = ()) -> list[Write]`. Here `prev=None` means the cache is uncertain, so the whole frame is repainted. frameEnd is **not** included.
  - `ResyncRotor(valid: frozenset[int], per_frame: int = 3)` with `.next() -> tuple[int, ...]`

Ruling carried from the spec: `frame.py` is built before Gate A because the gate's fps test must send realistic frames. Gate A confirms the fn 1/fn 5 layouts. If it contradicts them, Part 2 fixes `frame.py` and its tests.

- [ ] **Step 1: Write the failing tests**

```python
# g560ctl/test/test_new_g815_frame.py
from logitech_lighting.devices.g815.frame import (
    FN_SET_INDIVIDUAL, FN_SET_RANGE, FN_SET_SINGLE, ResyncRotor, encode,
)

R, B, W = (255, 0, 0), (0, 0, 255), (255, 255, 255)
VALID = frozenset(range(1, 40)) | {0x68, 0xB4, 0xD2}


def _zones_painted(writes):
    painted = {}
    for fn, p in writes:
        assert len(p) <= 16
        if fn == FN_SET_RANGE:
            for i in range(0, len(p), 5):
                s, e, r, g, b = p[i:i + 5]
                for z in range(s, e + 1):
                    painted.setdefault(z, []).append((r, g, b))
        elif fn == FN_SET_SINGLE:
            color = tuple(p[:3])
            for z in sorted(set(p[3:])):
                painted.setdefault(z, []).append(color)
        elif fn == FN_SET_INDIVIDUAL:
            for i in range(0, len(p), 4):
                z, r, g, b = p[i:i + 4]
                painted.setdefault(z, []).append((r, g, b))
    return painted


def test_no_change_no_packets() -> None:
    frame = {1: R, 2: R}
    assert encode(frame, dict(frame), VALID) == []


def test_run_of_three_uses_range() -> None:
    writes = encode({1: B, 2: B, 3: B}, {1: R, 2: R, 3: R}, VALID)
    assert writes == [(FN_SET_RANGE, bytes([1, 3, 255, 0, 0]))]


def test_scattered_shared_color_uses_single_value_padded_with_own_zone() -> None:
    nxt = {1: R, 5: R, 9: R, 13: R}
    writes = encode({z: B for z in nxt}, nxt, VALID)
    assert writes == [(FN_SET_SINGLE, bytes([255, 0, 0, 1, 5, 9, 13] + [1] * 9))]


def test_singletons_use_individual_four_per_packet() -> None:
    prev = {1: B, 3: B, 5: B, 7: B, 9: B}
    nxt = {1: (1, 1, 1), 3: (2, 2, 2), 5: (3, 3, 3), 7: (4, 4, 4), 9: (5, 5, 5)}
    writes = encode(prev, nxt, VALID)
    assert [fn for fn, _ in writes] == [FN_SET_INDIVIDUAL, FN_SET_INDIVIDUAL]
    assert writes[0][1] == bytes([1, 1, 1, 1, 3, 2, 2, 2, 5, 3, 3, 3, 7, 4, 4, 4])
    assert writes[1][1] == bytes([9, 5, 5, 5])


def test_invalid_zones_never_emitted() -> None:
    nxt = {1: R, 2: R, 0x50: R, 0xFE: R}
    painted = _zones_painted(encode(None, nxt, VALID))
    assert set(painted) == {1, 2}


def test_range_never_spans_invalid_zone() -> None:
    valid = frozenset({1, 2, 3, 5, 6, 7})                 # 4 is missing
    nxt = {z: R for z in range(1, 8)}
    for fn, p in encode(None, nxt, valid):
        if fn == FN_SET_RANGE:
            for i in range(0, len(p), 5):
                assert not (p[i] <= 4 <= p[i + 1])


def test_full_repaint_covers_every_valid_zone_once() -> None:
    nxt = {z: W for z in VALID}
    painted = _zones_painted(encode(None, nxt, VALID))
    assert set(painted) == set(VALID)
    assert all(colors == [W] for colors in painted.values())


def test_uncertain_cache_repaints_everything() -> None:
    nxt = {z: R for z in range(1, 6)}
    assert set(_zones_painted(encode(None, nxt, VALID))) == set(range(1, 6))


def test_resync_zones_are_resent_unchanged() -> None:
    frame = {1: R, 2: B, 3: R}
    painted = _zones_painted(encode(frame, dict(frame), VALID, resync=(2,)))
    assert painted == {2: [B]}


def test_resync_rotor_cycles_all_zones() -> None:
    rotor = ResyncRotor(frozenset({1, 2, 3, 4, 5}), per_frame=2)
    seen = [z for _ in range(3) for z in rotor.next()]
    assert seen == [1, 2, 3, 4, 5, 1]
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_frame.py -q`
Expected: FAIL with `ModuleNotFoundError: ... frame`

- [ ] **Step 3: Write the implementation**

```python
# g560ctl/src/logitech_lighting/devices/g815/frame.py
"""Encode a lighting frame into the fewest HID++ 0x8081 writes.

Byte layouts (Solaar PerKeyLighting, OpenRGB LogitechHIDPP20Controller):
  fn 5 setRangeRgbZones      [start, end, r, g, b] x <=3
  fn 6 setRgbZonesSingleValue [r, g, b, zone x 13]  (short packets repeat their own zone)
  fn 1 setIndividualRgbZones [zone, r, g, b] x <=4
frameEnd (fn 7) is sent by the transport after every write is acknowledged.
"""
from __future__ import annotations

from logitech_lighting.devices.g815.presets import Color

FN_SET_INDIVIDUAL = 1
FN_SET_RANGE = 5
FN_SET_SINGLE = 6
FN_FRAME_END = 7

Write = tuple[int, bytes]


def _runs(zones: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for z in zones:
        if runs and z == runs[-1][-1] + 1:
            runs[-1].append(z)
        else:
            runs.append([z])
    return runs


def encode(
    prev: dict[int, Color] | None,
    nxt: dict[int, Color],
    valid: frozenset[int],
    resync: tuple[int, ...] = (),
) -> list[Write]:
    changed = {
        z: c for z, c in nxt.items()
        if z in valid and (prev is None or prev.get(z) != c)
    }
    for z in resync:
        if z in valid and z in nxt:
            changed[z] = nxt[z]

    by_color: dict[Color, list[int]] = {}
    for z in sorted(changed):
        by_color.setdefault(changed[z], []).append(z)

    ranges: list[bytes] = []
    singles: list[bytes] = []
    for color in sorted(by_color):
        leftover: list[int] = []
        # A run only joins consecutive zones that are all in `valid`, because
        # `changed` only holds valid zones and runs need z == previous + 1.
        for run in _runs(by_color[color]):
            if len(run) >= 3:
                ranges.append(bytes([run[0], run[-1], *color]))
            else:
                leftover.extend(run)
        while len(leftover) >= 4:
            chunk, leftover = leftover[:13], leftover[13:]
            chunk = chunk + [chunk[0]] * (13 - len(chunk))
            singles.append(bytes([FN_SET_SINGLE, *color, *chunk]))
        for z in leftover:
            singles.append(bytes([FN_SET_INDIVIDUAL, z, *color]))

    writes: list[Write] = []
    for i in range(0, len(ranges), 3):
        writes.append((FN_SET_RANGE, b"".join(ranges[i:i + 3])))
    individual = b""
    for item in singles:
        if item[0] == FN_SET_SINGLE:
            writes.append((FN_SET_SINGLE, item[1:]))
        else:
            individual += item[1:]
            if len(individual) == 16:
                writes.append((FN_SET_INDIVIDUAL, individual))
                individual = b""
    if individual:
        writes.append((FN_SET_INDIVIDUAL, individual))
    return writes


class ResyncRotor:
    """Hands out a few zones per frame, cycling through every valid zone."""

    def __init__(self, valid: frozenset[int], per_frame: int = 3) -> None:
        self._zones = sorted(valid)
        self._per_frame = per_frame
        self._pos = 0

    def next(self) -> tuple[int, ...]:
        out = []
        for _ in range(min(self._per_frame, len(self._zones))):
            out.append(self._zones[self._pos])
            self._pos = (self._pos + 1) % len(self._zones)
        return tuple(out)
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_frame.py -q`
Expected: `10 passed`

- [ ] **Step 5: Run the full suite**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `59 passed` (27 existing + 32 new)

- [ ] **Step 6: Commit**

```bash
git add g560ctl/src/logitech_lighting/devices/g815/frame.py g560ctl/test/test_new_g815_frame.py
git commit -m "feat(g815): minimal HID++ frame encoder (range/single/individual)"
```

---

### Task 5: Gate A — claim sequence and committed fps (hardware)

**Files:**
- Create: `experiments/g815_gate_a.py`
- Modify: `docs/superpowers/specs/2026-10-13-g815-wave-design.md` (append a dated "Gate A results" section)

**Interfaces:**
- Consumes: `layout.KEYS`, `layout.PHASE1_VALID_ZONES`, `presets.PRESETS`, `presets.BASE`, `ripple.Ripple`, `frame.encode`, `frame.ResyncRotor`, `frame.FN_FRAME_END`
- Produces: the recorded facts that Part 2 consumes:
  - the verified claim bytes;
  - whether `0x4522` is needed;
  - the G-key behaviour in host mode;
  - which writes echo their payload;
  - the ping echo;
  - reply ordering;
  - the discovered zone set;
  - the media-key order;
  - committed fps.

This probe is throwaway (like `experiments/g815_probe.py`). It has its own minimal sender with a rotating sw_id and a fixed pipelining window. It is **not** the Part 2 transport.

- [ ] **Step 1: Write the probe**

```python
#!/usr/bin/env python3
"""Gate A probe: verify the G815 claim sequence, write echoes, and committed fps.

Throwaway, like experiments/g815_probe.py. Run with the project venv:
  g560ctl/.venv/bin/python experiments/g815_gate_a.py <subcommand>
"""
import argparse
import random
import sys
import time

import hidraw  # never `hid` (libusb backend detaches the keyboard driver)

from logitech_lighting.devices.g815.frame import FN_FRAME_END, ResyncRotor, encode
from logitech_lighting.devices.g815.layout import BY_NAME, KEYS, PHASE1_VALID_ZONES
from logitech_lighting.devices.g815.presets import BASE, PRESETS
from logitech_lighting.devices.g815.ripple import Ripple

VID, PID = 0x046D, 0xC33F
FEATURES = {"root": 0x0000, "perkey": 0x8081, "effects": 0x8071, "onboard": 0x8100, "disable_keys": 0x4522}
SW_ACTIVE, SW_RELEASE = bytes([0x01, 0x03, 0x04]), bytes([0x01, 0x00, 0x00])


class Dev:
    def __init__(self):
        entry = next(e for e in hidraw.enumerate(VID, PID)
                     if e["usage_page"] == 0xFF43 and e["usage"] == 0x0602)
        self.h = hidraw.device()
        self.h.open_path(entry["path"])
        self.sw = 0
        self.idx = {}

    def next_sw(self):
        self.sw = self.sw % 15 + 1
        return self.sw

    def report(self, feat, fn, params=b"", sw=None):
        sw = self.next_sw() if sw is None else sw
        return (bytes([0x11, 0xFF, feat, (fn << 4) | sw]) + bytes(params)).ljust(20, b"\x00")

    def read(self, ms):
        r = bytes(self.h.read(64, ms))
        return r if len(r) >= 6 and r[0] == 0x11 else None

    def request(self, feat, fn, params=b"", timeout=1.0):
        """Send one request, wait for its reply; return (kind, reply)."""
        rep = self.report(feat, fn, params)
        self.h.write(rep)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r = self.read(50)
            if r is None:
                continue
            if r[2] == 0xFF and r[3] == rep[2] and r[4] == rep[3]:
                return "error", r
            if r[2] == rep[2] and r[3] == rep[3]:
                return "ok", r
        return "timeout", None

    def discover(self):
        for name, fid in FEATURES.items():
            if name == "root":
                self.idx[name] = 0
                continue
            kind, r = self.request(0, 0, fid.to_bytes(2, "big"))
            self.idx[name] = r[4] if kind == "ok" and r[4] else None
        return self.idx


def cmd_claim(args):
    d = Dev()
    print("features:", {k: (hex(v) if v is not None else None) for k, v in d.discover().items()})
    if d.idx["onboard"]:
        print("onboard host mode:", d.request(d.idx["onboard"], 1, b"\x02")[0])
    if d.idx["effects"] and not args.no_sw_control:
        print("SetSWControl SW_ACTIVE:", d.request(d.idx["effects"], 5, SW_ACTIVE)[0])
    zones = set()
    for page in range(3):
        kind, r = d.request(d.idx["perkey"], 0, bytes([0x00, page, 0x00]))
        if kind != "ok":
            print(f"zone page {page}: {kind}")
            continue
        bitmap = r[6:20]
        zones |= {page * 112 + i * 8 + b for i, byte in enumerate(bitmap) for b in range(8) if byte >> b & 1}
    print("discovered zones:", len(zones), "== phase1:", zones == set(PHASE1_VALID_ZONES))
    print("  only discovered:", sorted(hex(z) for z in zones - PHASE1_VALID_ZONES))
    print("  only phase1:    ", sorted(hex(z) for z in PHASE1_VALID_ZONES - zones))
    base = {k.zone: BASE for k in KEYS}
    for fn, params in encode(None, base, frozenset(PHASE1_VALID_ZONES)):
        print(f"  base write fn{fn}:", d.request(d.idx["perkey"], fn, params)[0])
    print("frameEnd:", d.request(d.idx["perkey"], FN_FRAME_END, b"\x00")[0])
    print("base painted; watch the keyboard for 60 s without touching anything")


def cmd_release(args):
    d = Dev()
    d.discover()
    if d.idx["effects"]:
        print("SetSWControl release:", d.request(d.idx["effects"], 5, SW_RELEASE)[0])
    if d.idx["onboard"]:
        print("onboard mode:", d.request(d.idx["onboard"], 1, b"\x01")[0])


def cmd_zone(args):
    d = Dev()
    d.discover()
    zone, rgb = int(args.zone, 16), bytes.fromhex(args.color)
    print("fn1:", d.request(d.idx["perkey"], 1, bytes([zone]) + rgb)[0])
    print("frameEnd:", d.request(d.idx["perkey"], FN_FRAME_END, b"\x00")[0])


def cmd_echo(args):
    d = Dev()
    d.discover()
    pk = d.idx["perkey"]
    probes = {
        "fn1 individual": (1, bytes([0x01, 0x10, 0x20, 0x30])),
        "fn5 range": (5, bytes([0x02, 0x04, 0x40, 0x50, 0x60])),
        "fn6 single": (6, bytes([0x70, 0x80, 0x90] + [0x05] * 13)),
    }
    for name, (fn, params) in probes.items():
        kind, r = d.request(pk, fn, params)
        echoed = kind == "ok" and r[4:4 + len(params)] == params
        print(f"{name}: {kind}, echoes params: {echoed}, reply params: {r[4:20].hex(' ') if r else None}")
    print("frameEnd:", d.request(pk, FN_FRAME_END, b"\x00")[0])
    ping = random.randrange(1, 256)
    kind, r = d.request(0, 1, bytes([0x00, 0x00, ping]))
    print(f"ping {ping:#04x}: {kind}, echoed byte at params[2]: {r[6] == ping if r else None}")
    # Ordering: 6 pipelined fn1 writes with distinct colors; record reply order.
    sent = []
    for i in range(6):
        rep = d.report(pk, 1, bytes([0x01, i, i, i]))
        d.h.write(rep)
        sent.append(rep[3])
    got, end = [], time.monotonic() + 1.0
    while len(got) < 6 and time.monotonic() < end:
        r = d.read(50)
        if r is not None and r[2] == pk:
            got.append(r[3])
    print("ordering: sent", [hex(s) for s in sent], "got", [hex(g) for g in got], "in order:", got == sent)
    d.request(pk, FN_FRAME_END, b"\x00")


def cmd_fps(args):
    d = Dev()
    d.discover()
    pk = d.idx["perkey"]
    valid = frozenset(PHASE1_VALID_ZONES)
    ripple = Ripple(preset=PRESETS[args.preset])
    rotor = ResyncRotor(valid)
    names = [k.name for k in KEYS if k.evdev is not None and len(k.name) == 1]
    prev = None
    committed = abandoned = busy_end = writes_total = 0
    next_press = start = time.monotonic()
    while (now := time.monotonic()) - start < args.seconds:
        while next_press <= now:                       # synthetic fast typing
            ripple.press(random.choice(names), next_press)
            next_press += 1.0 / args.rate
        nxt = ripple.render(now)
        writes = encode(prev, nxt, valid, rotor.next())
        writes_total += len(writes)
        pending, ok, queue = {}, True, list(writes)
        deadline = now + 0.060
        while (queue or pending) and ok:
            while queue and len(pending) < args.window:
                fn, params = queue.pop(0)
                rep = d.report(pk, fn, params)
                d.h.write(rep)
                pending[rep[3]] = rep
            if time.monotonic() > deadline:
                ok = False
                break
            r = d.read(5)
            if r is None:
                continue
            if r[2] == 0xFF and r[4] in pending:
                ok = False
            elif r[2] == pk and r[3] in pending:
                pending.pop(r[3])
        if not ok:
            abandoned += 1
            prev = None
            time.sleep(0.05)
            while d.read(5) is not None:                # drain
                pass
            continue
        end = time.monotonic() + 0.150
        while time.monotonic() < end:
            kind, _ = d.request(pk, FN_FRAME_END, b"\x00", timeout=0.05)
            if kind == "ok":
                committed += 1
                prev = nxt
                break
            busy_end += 1
            time.sleep(0.003)
        else:
            prev = None
    elapsed = time.monotonic() - start
    print(f"{committed} committed frames in {elapsed:.1f}s = {committed / elapsed:.1f} fps "
          f"(window {args.window}, {args.rate}/s presses, {writes_total / max(committed, 1):.1f} writes/frame, "
          f"{abandoned} abandoned, {busy_end} frameEnd retries)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("claim"); s.add_argument("--no-sw-control", action="store_true"); s.set_defaults(f=cmd_claim)
    sub.add_parser("release").set_defaults(f=cmd_release)
    s = sub.add_parser("zone"); s.add_argument("zone"); s.add_argument("color"); s.set_defaults(f=cmd_zone)
    sub.add_parser("echo").set_defaults(f=cmd_echo)
    s = sub.add_parser("fps")
    s.add_argument("--seconds", type=float, default=10.0)
    s.add_argument("--rate", type=float, default=12.0)
    s.add_argument("--window", type=int, default=4)
    s.add_argument("--preset", default="red", choices=sorted(PRESETS))
    s.set_defaults(f=cmd_fps)
    args = p.parse_args(argv)
    args.f(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-check offline**

Run: `g560ctl/.venv/bin/python experiments/g815_gate_a.py --help`
Expected: the subcommands `claim, release, zone, echo, fps` are listed, with no traceback.

- [ ] **Step 3: Hardware run — claim with SetSWControl and the 60 s hold**

Run: `g560ctl/.venv/bin/python experiments/g815_gate_a.py claim`
Ask the user to watch for 60 s. Expected:
- every line prints `ok`;
- `discovered zones: ... == phase1: True`, or record the differences;
- the whole keyboard turns base `#140028` and **stays** that color for 60 s, including the G-keys and logo.

Record which features were found (including whether `disable_keys` 0x4522 exists).

- [ ] **Step 4: Hardware run — without SetSWControl**

Run `... release`, then `... claim --no-sw-control`, then ask the user to watch for 60 s.
Record whether colors revert to the onboard effect. If they revert, SetSWControl is required. If the G-keys or other keys misbehave in both runs, record it: the `0x4522` handshake is then needed, and Part 2 must research its bytes before continuing.

- [ ] **Step 5: Hardware run — echo, ping and ordering**

Run: `... claim`, then `... echo`
Record per write whether it `echoes params`, whether the ping byte echoed, and whether `ordering ... in order: True`.

- [ ] **Step 6: Hardware run — media-key order**

Run, one at a time, asking the user which key lit:
- `... zone 9b ffffff`
- `... zone 9c ffffff`
- `... zone 9d ffffff`
- `... zone 9e ffffff`

If it differs from `layout.py` (`9b` play, `9c` mute, `9d` next, `9e` prev), record the real order. Part 2 corrects `layout.py`.

- [ ] **Step 7: Hardware run — committed fps (the gate)**

Run: `... fps --seconds 10 --window 4`, then `... fps --seconds 10 --window 8`, then `... fps --seconds 10 --window 4 --rate 20`. Ask the user to confirm that ripples are visible.
Expected: a line `N committed frames in 10.0s = X fps ...`. **The gate passes at ≥ 30 committed fps** with the default rate (12 presses/s, 8 overlapping rings).
If it fails, re-run with coarser effect settings and record the best combination that reaches 30:
- `U_STEPS` 4;
- `BAND` 2.0.

Change these values in a scratch copy, not in the committed modules.
Then run `... release` and confirm the onboard effect returns.

- [ ] **Step 8: Record Gate A results in the spec**

Append to `docs/superpowers/specs/2026-10-13-g815-wave-design.md`:

```markdown
## Gate A results (2026-10-13)

- Features found: 0x8081 → idx …, 0x8071 → idx …, 0x8100 → idx …, 0x4522 → present/absent
- Claim: host mode `0x8100 fn1 [02]` → ok/…; SetSWControl `0x8071 fn5 [01 03 04]` → ok/…
- Without SetSWControl: colors revert after … s / stay
- 0x4522 handshake needed: yes/no (evidence: …)
- G-keys in host mode: lit correctly / broken
- Zone discovery: matches Phase 1 / differences: …
- Write echo: fn1 …, fn5 …, fn6 …; ping byte echoed: yes/no; reply ordering: in order / reordered
- Media keys: 0x9b … 0x9c … 0x9d … 0x9e …
- Committed fps: window 4 → … fps, window 8 → … fps, rate 20 → … fps (writes/frame …, abandoned …, frameEnd retries …)
- Gate verdict: PASS / FAIL (+ chosen fallback values)
```

Replace every `…` and every `/` choice with the observed result. Then:

```bash
git add experiments/g815_gate_a.py docs/superpowers/specs/2026-10-13-g815-wave-design.md
git commit -m "feat(experiments): G815 Gate A probe and recorded results"
```

**If Gate A fails, stop here.** Report to the user and revise the spec before Task 6.

---

### Task 6: Gate B — XI2 raw keypress input (X11)

**Files:**
- Create: `experiments/g815_gate_b.py`
- Modify: `g560ctl/pyproject.toml` (add `python-xlib>=0.29` to `dependencies`)
- Modify: `docs/superpowers/specs/2026-10-13-g815-wave-design.md` (append "Gate B results")

**Interfaces:**
- Consumes: `layout.BY_EVDEV` (Task 1)
- Produces: the recorded facts Part 2's `keys.py` consumes:
  - the negotiated XI version;
  - that raw events are received and decoded;
  - that `sourceid` filtering works;
  - that events still arrive under grabs;
  - that ids re-resolve on hotplug.

- [ ] **Step 1: Add the dependency and install it**

In `g560ctl/pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
  "pyusb>=1.2",
  "python-xlib>=0.29",
]
```

Run: `g560ctl/.venv/bin/pip install -e g560ctl -q && g560ctl/.venv/bin/python -c "import Xlib; print(Xlib.__version__)"`
Expected: `(0, 29)` or newer.

- [ ] **Step 2: Write the probe**

```python
#!/usr/bin/env python3
"""Gate B probe: XI2.2 raw key presses from the G815 only, via python-xlib.

python-xlib 0.29's helper negotiates XI 2.0 and has no RawKeyPress decoder,
so this negotiates 2.2 itself (FIRST, before any other XI call) and registers
its own decoder for XI_RawKeyPress.
Run: g560ctl/.venv/bin/python experiments/g815_gate_b.py
Prints only key NAMES for G815 presses (never logs anything else).
"""
import sys

from Xlib import display
from Xlib.ext import xinput
from Xlib.protocol import rq

from logitech_lighting.devices.g815.layout import BY_EVDEV

G815_NAME = "Logitech G815 RGB MECHANICAL GAMING KEYBOARD"
RAW_KEY_PRESS = 13          # XI_RawKeyPress
HIERARCHY_CHANGED = 11      # XI_HierarchyChanged

RawKeyEventData = rq.Struct(
    rq.Card16("deviceid"),
    rq.Card32("time"),
    rq.Card32("detail"),
    rq.Card16("sourceid"),
    rq.Card16("valuators_len"),
    rq.Card32("flags"),
    rq.Pad(4),
)


def g815_ids(d):
    info = d.xinput_query_device(xinput.AllDevices)
    return {dev.deviceid for dev in info.devices
            if dev.name.startswith(G815_NAME) and dev.use == xinput.SlaveKeyboard}


def main():
    d = display.Display()
    opcode = d.get_extension_major("XInputExtension")
    v = xinput.XIQueryVersion(display=d.display, opcode=opcode, major_version=2, minor_version=2)
    print(f"XI negotiated {v.major_version}.{v.minor_version}")
    if (v.major_version, v.minor_version) < (2, 1):
        print("FAIL: server XI < 2.1")
        return 1
    d.ge_add_event_data(opcode, RAW_KEY_PRESS, RawKeyEventData)  # method lives on Display, not d.display
    root = d.screen().root
    root.xinput_select_events([
        (xinput.AllMasterDevices, 1 << RAW_KEY_PRESS),
        (xinput.AllDevices, 1 << HIERARCHY_CHANGED),
    ])
    ids = g815_ids(d)
    print("G815 slave keyboard ids:", sorted(ids))
    while True:
        ev = d.next_event()
        if getattr(ev, "evtype", None) == HIERARCHY_CHANGED:
            ids = g815_ids(d)
            print("hierarchy changed; G815 ids now:", sorted(ids))
        elif getattr(ev, "evtype", None) == RAW_KEY_PRESS:
            data = ev.data
            if data.sourceid not in ids:
                print("(ignored: other device)")
                continue
            key = BY_EVDEV.get(data.detail - 8)
            print("G815 press:", key.name if key else "(unmapped)")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
```

- [ ] **Step 3: Run and check the basics**

Run in the background: `g560ctl/.venv/bin/python experiments/g815_gate_b.py` (Ctrl-C or kill to stop)
Expected:
- `XI negotiated 2.2` (any ≥ 2.1 passes);
- `G815 slave keyboard ids: [15, 16]` (current ids);
- typing `a s d space` on the G815 prints `G815 press: a` … `G815 press: space`.

If `ev.data` has no `sourceid` (the decoder is not used), print `type(ev)` and `ev.__dict__`, record it, and fix the event registration before continuing.

- [ ] **Step 4: Other-device filtering and grabs**

- Ask the user to press a button on the G502 mouse that sends keys, if one is mapped. The probe should print `(ignored: other device)` or nothing.
- Ask the user to open the GNOME overview (Super) and type a few letters there, then open an application menu and press keys. Each press must still print `G815 press: …`.

- [ ] **Step 5: Hotplug re-resolution**

Ask the user to unplug and replug the G815 while the probe runs.
Expected: one or more `hierarchy changed; G815 ids now: [...]` lines, then presses still print.

- [ ] **Step 6: Record Gate B results and commit**

Append to the spec:

```markdown
## Gate B results (2026-10-13)

- XI negotiated: …
- Raw decode: deviceid/detail/sourceid fields valid: yes/no
- G815 ids at start: …; filtering of other devices: works/fails
- Events under grab (overview, menu): received / missed
- Hotplug: ids re-resolved to …; presses after replug: yes/no
- Keycode mapping (X keycode - 8 = evdev → layout): correct for … / wrong for …
- Gate verdict: PASS / FAIL
```

Replace every `…` and every `/` choice with the observed result. Then:

```bash
git add experiments/g815_gate_b.py g560ctl/pyproject.toml docs/superpowers/specs/2026-10-13-g815-wave-design.md
git commit -m "feat(experiments): G815 Gate B XI2 raw-input probe and recorded results"
```

**After Task 6:** if both gates pass, the next step is writing Part 2's plan (`hidpp.py`, `state.py`, `keys.py`, `daemon.py`, CLI `wave`, the systemd unit, docs) from the recorded results. If a gate fails, revise the spec first.
