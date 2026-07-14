from __future__ import annotations

from .colors import clamp_brightness, clamp_rate
from .device import G560Transport
from .models import Color, LightingRequest, Mode, Zone
from .zones import ZONE_TO_DEVICE_ID


class G560Controller:
    def __init__(self, transport: G560Transport | None = None) -> None:
        self.transport = transport or G560Transport()

    def apply(self, request: LightingRequest) -> None:
        session = self.transport.open()
        try:
            for zone in request.zones:
                payload = self._payload_for(zone, request)
                self.transport.send_packet(session, payload)
        finally:
            session.close()

    def off(self, zones: frozenset[Zone]) -> LightingRequest:
        request = LightingRequest(
            mode=Mode.OFF,
            zones=zones,
            color=Color("000000"),
        )
        self.apply(request)
        return request

    def solid(self, color: Color, zones: frozenset[Zone]) -> LightingRequest:
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
        zones: frozenset[Zone],
        rate_ms: int = 3000,
        brightness: int = 100,
    ) -> LightingRequest:
        request = LightingRequest(
            mode=Mode.BREATHE,
            zones=zones,
            color=color,
            rate_ms=clamp_rate(rate_ms),
            brightness=clamp_brightness(brightness),
        )
        self.apply(request)
        return request

    def cycle(
        self,
        zones: frozenset[Zone],
        rate_ms: int = 8000,
        brightness: int = 100,
    ) -> LightingRequest:
        request = LightingRequest(
            mode=Mode.CYCLE,
            zones=zones,
            rate_ms=clamp_rate(rate_ms),
            brightness=clamp_brightness(brightness),
        )
        self.apply(request)
        return request

    def _payload_for(self, zone: Zone, request: LightingRequest) -> str:
        zone_hex = ZONE_TO_DEVICE_ID[zone]

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

        return self.transport.make_payload(zone_hex, mode_hex, data_hex)