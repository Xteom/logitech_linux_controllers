from dataclasses import dataclass

from logitech_lighting import UnifiedController, get_device_config, parse_color, resolve_zones
from logitech_lighting.core.models import Mode
from logitech_lighting.core.transport import DeviceSession


@dataclass
class FakeSession:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, vendor_id: int, product_id: int, interface: int) -> None:
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.interface = interface
        self.session = FakeSession()
        self.payloads: list[str] = []

    def open(self) -> FakeSession:
        return self.session

    def send_packet(self, session: FakeSession, payload_hex: str) -> None:
        self.payloads.append(payload_hex)


def test_solid_generates_payloads_per_zone() -> None:
    config = get_device_config("g560")
    transport = FakeTransport(config.vendor_id, config.product_id, config.interface)
    controller = UnifiedController(config, transport=transport)
    zones = resolve_zones("left_primary,right_primary", config)

    request = controller.solid(parse_color("ff0000"), zones)

    assert request.mode == Mode.SOLID
    assert len(transport.payloads) == 2
    assert "11ff043a0201ff00000000000000000000000000" in transport.payloads
    assert "11ff043a0301ff00000000000000000000000000" in transport.payloads
    assert transport.session.closed is True


def test_off_uses_black_solid() -> None:
    config = get_device_config("g560")
    transport = FakeTransport(config.vendor_id, config.product_id, config.interface)
    controller = UnifiedController(config, transport=transport)
    zones = resolve_zones("left_secondary", config)

    request = controller.off(zones)

    assert request.mode == Mode.OFF
    assert transport.payloads == ["11ff043a00010000000000000000000000000000"]


def test_breathe_payload() -> None:
    config = get_device_config("g560")
    transport = FakeTransport(config.vendor_id, config.product_id, config.interface)
    controller = UnifiedController(config, transport=transport)
    zones = resolve_zones("right_secondary", config)

    controller.breathe(parse_color("00aaff"), zones, rate_ms=3000, brightness=80)

    assert transport.payloads == ["11ff043a010400aaff0bb8005000000000000000"]


def test_cycle_payload() -> None:
    config = get_device_config("g560")
    transport = FakeTransport(config.vendor_id, config.product_id, config.interface)
    controller = UnifiedController(config, transport=transport)
    zones = resolve_zones("right_primary", config)

    controller.cycle(zones, rate_ms=8000, brightness=100)

    assert transport.payloads == ["11ff043a030200000000001f4064000000000000"]
