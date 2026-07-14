"""DEAD CODE — tests for the legacy ``g560ctl`` package modules.

The runtime path is the ``logitech_lighting`` package (see the ``test_new_*.py``
suite). These tests cover superseded modules and are kept only so the legacy
code stays green — do not add coverage here.
"""

from g560ctl.colors import clamp_brightness, clamp_rate, parse_color
from g560ctl.models import ValidationError


def test_parse_color_accepts_hash() -> None:
    color = parse_color("#ff6600")
    assert color.hex_value == "ff6600"
    assert color.rgb == (255, 102, 0)


def test_parse_color_rejects_invalid() -> None:
    try:
        parse_color("zzzzzz")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_clamp_rate() -> None:
    assert clamp_rate(50) == 100
    assert clamp_rate(3000) == 3000
    assert clamp_rate(999999) == 65535


def test_clamp_brightness() -> None:
    assert clamp_brightness(0) == 1
    assert clamp_brightness(50) == 50
    assert clamp_brightness(101) == 100