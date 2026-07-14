"""DEAD CODE — legacy G560-only module, not on the runtime path.

Superseded by ``logitech_lighting.core.colors``. Both console scripts
(``g560ctl`` and ``logitech-lighting``) run the ``logitech_lighting`` package;
``g560ctl/cli.py`` is only a thin shim that imports it. This module is retained
for reference and is exercised solely by the legacy ``test/`` suite — do not
extend it.
"""

from __future__ import annotations

from .models import Color, ValidationError

# G560-specific preset colors (kept for backward compatibility)
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
    """Clamp rate to G560's valid range (100-65535ms).
    
    Kept for backward compatibility with old g560ctl code.
    """
    try:
        rate = int(rate_ms)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Rate must be an integer") from exc
    return max(100, min(65535, rate))


def clamp_brightness(brightness: int) -> int:
    """Clamp brightness to G560's valid range (1-100%).
    
    Kept for backward compatibility with old g560ctl code.
    """
    try:
        value = int(brightness)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Brightness must be an integer") from exc
    return max(1, min(100, value))