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
