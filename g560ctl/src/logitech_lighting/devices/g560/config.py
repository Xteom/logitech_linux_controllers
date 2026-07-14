from __future__ import annotations

from dataclasses import dataclass

from logitech_lighting.core.exceptions import ValidationError
from logitech_lighting.core.models import LightingRequest, Mode

VENDOR_ID = 0x046D
PRODUCT_ID = 0x0A78
INTERFACE = 0x02

PREFIX = "11ff043a"
SUFFIX = "000000000000"

ZONES = {
    "left_secondary": "00",
    "right_secondary": "01",
    "left_primary": "02",
    "right_primary": "03",
}

ZONE_LABELS = {
    "left_secondary": "Left rear",
    "right_secondary": "Right rear",
    "left_primary": "Left front",
    "right_primary": "Right front",
}

ZONE_ALIASES = {
    "all": (
        "left_secondary",
        "right_secondary",
        "left_primary",
        "right_primary",
    ),
    "left": (
        "left_secondary",
        "left_primary",
    ),
    "right": (
        "right_secondary",
        "right_primary",
    ),
    "primary": (
        "left_primary",
        "right_primary",
    ),
    "secondary": (
        "left_secondary",
        "right_secondary",
    ),
    "left_secondary": ("left_secondary",),
    "right_secondary": ("right_secondary",),
    "left_primary": ("left_primary",),
    "right_primary": ("right_primary",),
}

# G560-specific color presets
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


@dataclass
class G560Config:
    """Logitech G560 device configuration."""
    
    @property
    def name(self) -> str:
        return "Logitech G560"
    
    @property
    def vendor_id(self) -> int:
        return VENDOR_ID
    
    @property
    def product_id(self) -> int:
        return PRODUCT_ID
    
    @property
    def interface(self) -> int:
        return INTERFACE
    
    @property
    def zones(self) -> dict[str, str]:
        return ZONES
    
    @property
    def zone_labels(self) -> dict[str, str]:
        return ZONE_LABELS
    
    @property
    def zone_aliases(self) -> dict[str, tuple[str, ...]]:
        return ZONE_ALIASES
    
    @property
    def rate_range(self) -> tuple[int, int]:
        """G560 supports 100-65535ms rate range."""
        return (100, 65535)
    
    @property
    def brightness_range(self) -> tuple[int, int]:
        """G560 supports 1-100% brightness range."""
        return (1, 100)
    
    @property
    def preset_colors(self) -> list[tuple[str, str]]:
        """G560-optimized preset colors."""
        return PRESET_COLORS
    
    def clamp_rate(self, rate_ms: int) -> int:
        """Clamp rate to G560's valid range (100-65535ms)."""
        try:
            rate = int(rate_ms)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Rate must be an integer") from exc
        min_ms, max_ms = self.rate_range
        return max(min_ms, min(max_ms, rate))
    
    def clamp_brightness(self, brightness: int) -> int:
        """Clamp brightness to G560's valid range (1-100%)."""
        try:
            value = int(brightness)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Brightness must be an integer") from exc
        min_b, max_b = self.brightness_range
        return max(min_b, min(max_b, value))
    
    def build_payload(self, zone_name: str, request: LightingRequest) -> str:
        """Build G560-specific USB payload."""
        zone_hex = self.zones[zone_name]
        
        if request.mode == Mode.OFF:
            mode_hex = "01"
            data_hex = "000000" + "0000000000"
        elif request.mode == Mode.SOLID:
            assert request.color is not None
            mode_hex = "01"
            data_hex = request.color.hex_value + "0000000000"
        elif request.mode == Mode.BREATHE:
            assert request.color is not None
            assert request.rate_ms is not None
            assert request.brightness is not None
            mode_hex = "04"
            data_hex = (
                request.color.hex_value
                + f"{request.rate_ms:04x}"
                + "00"
                + f"{request.brightness:02x}"
                + "00"
            )
        elif request.mode == Mode.CYCLE:
            assert request.rate_ms is not None
            assert request.brightness is not None
            mode_hex = "02"
            data_hex = "0000000000" + f"{request.rate_ms:04x}" + f"{request.brightness:02x}"
        else:
            raise ValueError(f"Unsupported mode: {request.mode}")
        
        return PREFIX + zone_hex + mode_hex + data_hex + SUFFIX
