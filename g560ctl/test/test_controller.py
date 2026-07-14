from dataclasses import dataclass

from g560ctl.colors import parse_color
from g560ctl.controller import G560Controller
from g560ctl.models import LightingRequest, Mode
from g560ctl.zones import resolve_zones


@dataclass
class FakeSession:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self) -> None:
        self.session = FakeSession()
        self.payloads: list[str] = []

    def open(self) -> FakeSession:
        return self.session

    def send_packet(self, session: FakeSession, payload_hex: str) -> None:
        self.payloads.append(payload_hex)

    def make_payload(self, zone_hex: str, mode_hex: str, data_hex: str) -> str:
        return f"{zone_hex}:{mode_hex}:{data_hex}"


def test_solid_generates_payloads_per_zone() -> None:
    transport = FakeTransport()
    controller = G560Controller(transport=transport)
    zones = resolve_zones("left_primary,right_primary")

    request = controller.solid(parse_color("ff0000"), zones)

    assert request.mode == Mode.SOLID
    assert len(transport.payloads) == 2
    assert "02:01:ff00000000000000" in transport.payloads
    assert "03:01:ff00000000000000" in transport.payloads
    assert transport.session.closed is True


def test_off_uses_black_solid() -> None:
    transport = FakeTransport()
    controller = G560Controller(transport=transport)
    zones = resolve_zones("left_secondary")

    request = controller.off(zones)

    assert request.mode == Mode.OFF
    assert transport.payloads == ["00:01:0000000000000000"]


def test_breathe_payload() -> None:
    transport = FakeTransport()
    controller = G560Controller(transport=transport)
    zones = resolve_zones("right_secondary")

    controller.breathe(parse_color("00aaff"), zones, rate_ms=3000, brightness=80)

    assert transport.payloads == ["01:04:00aaff0bb8005000"]


def test_cycle_payload() -> None:
    transport = FakeTransport()
    controller = G560Controller(transport=transport)
    zones = resolve_zones("right_primary")

    controller.cycle(zones, rate_ms=8000, brightness=100)

    assert transport.payloads == ["03:02:00000000001f4064"]