from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet

from logitech_lighting.core.exceptions import ValidationError


class Mode(str, Enum):
    OFF = "off"
    SOLID = "solid"
    BREATHE = "breathe"
    CYCLE = "cycle"


@dataclass(frozen=True)
class Color:
    hex_value: str

    def __post_init__(self) -> None:
        value = self.hex_value.lower().lstrip("#")
        if len(value) != 6 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValidationError("Color must be a 6-digit hex RGB value, e.g. ff6600")
        object.__setattr__(self, "hex_value", value)

    @property
    def rgb(self) -> tuple[int, int, int]:
        return (
            int(self.hex_value[0:2], 16),
            int(self.hex_value[2:4], 16),
            int(self.hex_value[4:6], 16),
        )


@dataclass(frozen=True)
class LightingRequest:
    """Generic lighting request that works across devices."""
    mode: Mode
    zones: FrozenSet[str]  # Device-agnostic zone names
    color: Color | None = None
    rate_ms: int | None = None
    brightness: int | None = None


@dataclass
class SessionState:
    last_committed: LightingRequest | None = None
    last_previewed: LightingRequest | None = None
    errors: list[str] = field(default_factory=list)
