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
