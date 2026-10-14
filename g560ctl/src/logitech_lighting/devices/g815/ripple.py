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
