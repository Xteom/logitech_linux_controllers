from __future__ import annotations

from logitech_lighting.core.models import Color, LightingRequest, Mode
from logitech_lighting.core.transport import USBTransport
from logitech_lighting.devices.base import DeviceConfig


class UnifiedController:
    """Unified controller that works with any device configuration."""
    
    def __init__(self, device_config: DeviceConfig, transport: USBTransport | None = None):
        self.config = device_config
        self.transport = transport or USBTransport(
            vendor_id=device_config.vendor_id,
            product_id=device_config.product_id,
            interface=device_config.interface
        )
    
    def apply(self, request: LightingRequest) -> None:
        """Apply a lighting request to the device."""
        session = self.transport.open()
        try:
            for zone in request.zones:
                payload = self.config.build_payload(zone, request)
                self.transport.send_packet(session, payload)
        finally:
            session.close()
    
    def off(self, zones: frozenset[str]) -> LightingRequest:
        """Turn lights off."""
        request = LightingRequest(
            mode=Mode.OFF,
            zones=zones,
            color=Color("000000"),
        )
        self.apply(request)
        return request
    
    def solid(self, color: Color, zones: frozenset[str]) -> LightingRequest:
        """Set solid color."""
        request = LightingRequest(
            mode=Mode.SOLID,
            zones=zones,
            color=color,
        )
        self.apply(request)
        return request
    
    def breathe(
        self,
        color: Color,
        zones: frozenset[str],
        rate_ms: int = 3000,
        brightness: int = 100,
    ) -> LightingRequest:
        """Set breathing effect."""
        request = LightingRequest(
            mode=Mode.BREATHE,
            zones=zones,
            color=color,
            rate_ms=self.config.clamp_rate(rate_ms),
            brightness=self.config.clamp_brightness(brightness),
        )
        self.apply(request)
        return request
    
    def cycle(
        self,
        zones: frozenset[str],
        rate_ms: int = 8000,
        brightness: int = 100,
    ) -> LightingRequest:
        """Set color cycling effect."""
        request = LightingRequest(
            mode=Mode.CYCLE,
            zones=zones,
            rate_ms=self.config.clamp_rate(rate_ms),
            brightness=self.config.clamp_brightness(brightness),
        )
        self.apply(request)
        return request
