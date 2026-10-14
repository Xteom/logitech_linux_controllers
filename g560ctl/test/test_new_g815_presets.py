# g560ctl/test/test_new_g815_presets.py
from logitech_lighting.devices.g815.presets import (
    BASE, INTENSITY_STEPS, PRESETS, U_STEPS, gradient, lerp, quantize, ring_color,
)


def test_base_and_preset_stops() -> None:
    assert BASE == (0x1E, 0x00, 0x3C)   # #1e003c, brightened from #140028 (user, 2026-10-14)
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
