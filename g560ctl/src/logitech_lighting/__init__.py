"""Logitech lighting control library."""

from .controller import UnifiedController
from .core.colors import parse_color
from .core.exceptions import (
    DeviceNotFoundError,
    LogitechLightingError,
    PermissionDeniedError,
    TransferError,
    ValidationError,
)
from .core.models import Color, LightingRequest, Mode, SessionState
from .devices import get_device_config, discover_devices, get_default_device
from .utils import resolve_zones

__all__ = [
    "UnifiedController",
    "parse_color",
    "LogitechLightingError",
    "DeviceNotFoundError",
    "PermissionDeniedError",
    "TransferError",
    "ValidationError",
    "Color",
    "LightingRequest",
    "Mode",
    "SessionState",
    "get_device_config",
    "discover_devices",
    "get_default_device",
    "resolve_zones",
]
