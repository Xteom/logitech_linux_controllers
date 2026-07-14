from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from logitech_lighting.core.models import LightingRequest, Mode


class DeviceConfig(Protocol):
    """Protocol for device configuration."""
    
    @property
    def name(self) -> str:
        """Device name."""
        ...
    
    @property
    def vendor_id(self) -> int:
        """USB vendor ID."""
        ...
    
    @property
    def product_id(self) -> int:
        """USB product ID."""
        ...
    
    @property
    def interface(self) -> int:
        """USB interface number."""
        ...
    
    @property
    def zones(self) -> dict[str, str]:
        """Map of zone names to device-specific hex IDs."""
        ...
    
    @property
    def zone_labels(self) -> dict[str, str]:
        """Map of zone names to human-readable labels."""
        ...
    
    @property
    def zone_aliases(self) -> dict[str, tuple[str, ...]]:
        """Map of aliases to zone names."""
        ...
    
    @property
    def rate_range(self) -> tuple[int, int]:
        """Device-specific rate range in milliseconds (min, max)."""
        ...
    
    @property
    def brightness_range(self) -> tuple[int, int]:
        """Device-specific brightness range (min, max)."""
        ...
    
    @property
    def preset_colors(self) -> list[tuple[str, str]]:
        """Device-specific preset colors (name, hex)."""
        ...
    
    def clamp_rate(self, rate_ms: int) -> int:
        """Clamp rate to device-specific valid range."""
        ...
    
    def clamp_brightness(self, brightness: int) -> int:
        """Clamp brightness to device-specific valid range."""
        ...
    
    def build_payload(self, zone_name: str, request: LightingRequest) -> str:
        """Build device-specific payload for a zone and lighting request."""
        ...


@dataclass
class DeviceInfo:
    """Information about a discovered device."""
    config_id: str
    name: str
    vendor_id: int
    product_id: int
    connected: bool = False
