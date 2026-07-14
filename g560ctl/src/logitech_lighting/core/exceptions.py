from __future__ import annotations


class LogitechLightingError(Exception):
    """Base application error."""


class DeviceNotFoundError(LogitechLightingError):
    """Raised when a device is not found."""


class PermissionDeniedError(LogitechLightingError):
    """Raised when the USB interface cannot be claimed due to permissions."""


class TransferError(LogitechLightingError):
    """Raised when a USB control transfer fails."""


class ValidationError(LogitechLightingError):
    """Raised when user input is invalid."""
