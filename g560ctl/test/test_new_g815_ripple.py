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
