from __future__ import annotations

from logitech_lighting.core.exceptions import ValidationError
from logitech_lighting.core.models import Color


def parse_color(value: str) -> Color:
    """Parse a hex color string into a Color object.
    
    This is device-agnostic - RGB is RGB across all devices.
    """
    return Color(value)
