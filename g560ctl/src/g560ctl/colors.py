from __future__ import annotations

from .models import Color, ValidationError

PRESET_COLORS: list[tuple[str, str]] = [
    ("Red", "ff0000"),
    ("Orange", "ff6600"),
    ("Yellow", "ffd000"),
    ("Green", "00ff00"),
    ("Cyan", "00cfff"),
    ("Blue", "0000ff"),
    ("Purple", "7a00ff"),
    ("Pink", "ff33aa"),
    ("White", "ffffff"),
    ("Warm White", "ffe8b0"),
]


def parse_color(value: str) -> Color:
    return Color(value)


def clamp_rate(rate_ms: int) -> int:
    try:
        rate = int(rate_ms)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Rate must be an integer") from exc
    return max(100, min(65535, rate))


def clamp_brightness(brightness: int) -> int:
    try:
        value = int(brightness)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Brightness must be an integer") from exc
    return max(1, min(100, value))