import pytest

from g815_fakes import EFFECTS, ONBOARD, PERKEY, FakeClock, FakeKeyboardPort, ok_report
from logitech_lighting.devices.g815.hidpp import DeviceGone, Sender
from logitech_lighting.devices.g815.keyboard import (
    ClaimError, Connector, Keyboard, parse_zone_page, usable_zones,
)
from logitech_lighting.devices.g815.layout import BY_NAME, BY_ZONE, KEYS
from logitech_lighting.devices.g815.presets import BASE

BASE_FRAME = {k.zone: BASE for k in KEYS}


def _keyboard(**port_kw):
    clock = FakeClock()
    port = FakeKeyboardPort(clock, **port_kw)
    return Keyboard(Sender(port, clock=clock, sleep=clock.sleep)), port, clock


def _painted(port) -> set[int]:
    zones: set[int] = set()
    for p in port.requests(PERKEY, 5):
        for i in range(0, 15, 5):
            if p[i + 1]:
                zones |= set(range(p[i], p[i + 1] + 1))
    for p in port.requests(PERKEY, 6):
        zones |= set(p[3:16])
    for p in port.requests(PERKEY, 1):
        zones |= {p[i] for i in range(0, 16, 4) if any(p[i:i + 4])}
    return zones


def test_zone_page_bitmap_parsing() -> None:
    params = bytes([0, 1, 0b0000_0101] + [0] * 12 + [0b1000_0000])
    assert parse_zone_page(1, params) == {112, 114, 112 + 13 * 8 + 7}


def test_usable_zones_drops_zone_0_and_unknown_zones() -> None:
    assert usable_zones({0x00, 0x01, 0x2F, 0x99, 0xD2}) == frozenset({0x01, 0x99, 0xD2})


def test_claim_byte_sequence() -> None:
    kb, port, _ = _keyboard()
    kb.claim(BASE_FRAME)
    head = port.log[:8]
    assert head[:3] == [(0, 0, (f).to_bytes(2, "big").ljust(16, b"\x00")) for f in (0x8081, 0x8071, 0x8100)]
    assert head[3] == (EFFECTS, 5, bytes([1, 3, 4]).ljust(16, b"\x00"))
    assert head[4] == (ONBOARD, 1, bytes([2]).ljust(16, b"\x00"))
    assert [p[:3] for f, n, p in head[5:8]] == [bytes([0, page, 0]) for page in range(3)]
    assert port.log[-1][:2] == (PERKEY, 7)
    assert kb.valid == frozenset(BY_ZONE) and _painted(port) == set(BY_ZONE)
    assert kb.confirmed == BASE_FRAME and port.mode == 2


def test_release_reselects_profile() -> None:
    kb, port, _ = _keyboard()
    kb.claim(BASE_FRAME)
    n = len(port.log)
    kb.release()
    assert port.log[n:] == [
        (EFFECTS, 5, bytes([1, 0, 0]).ljust(16, b"\x00")),
        (ONBOARD, 1, bytes([1]).ljust(16, b"\x00")),
        (ONBOARD, 4, bytes(16)),
        (ONBOARD, 3, bytes([0, 1]).ljust(16, b"\x00")),
    ]
    assert port.mode == 1 and port.profile_selects == 1


def test_partial_claim_rolls_back() -> None:
    kb, port, _ = _keyboard()
    port.faults[(PERKEY, 0)] = ["error"]
    with pytest.raises(ClaimError):
        kb.claim(BASE_FRAME)
    assert [(f, n) for f, n, _ in port.log[-4:]] == [(EFFECTS, 5), (ONBOARD, 1), (ONBOARD, 4), (ONBOARD, 3)]
    assert port.mode == 1 and not kb.applied


def test_missing_perkey_feature_fails_claim() -> None:
    kb, port, _ = _keyboard(features={0x8071: 0x0F, 0x8100: 0x11})
    with pytest.raises(ClaimError):
        kb.claim(BASE_FRAME)
    assert not port.requests(EFFECTS)


def test_optional_features_absent_are_skipped_on_claim_release_and_check() -> None:
    kb, port, _ = _keyboard(features={0x8081: 0x10})
    kb.claim(BASE_FRAME)
    kb.check_control()
    kb.release()
    assert {f for f, _, _ in port.log} == {0x00, PERKEY}


def test_partial_frame_failure_means_no_frame_end_and_full_repaint() -> None:
    kb, port, _ = _keyboard()
    kb.claim(BASE_FRAME)
    frame = {**BASE_FRAME, BY_NAME["a"].zone: (255, 0, 0), BY_NAME["l"].zone: (0, 255, 0)}
    ends = len(port.requests(PERKEY, 7))
    port.faults[(PERKEY, 1)] = ["busy"]
    assert not kb.send_frame(frame)
    assert len(port.requests(PERKEY, 7)) == ends and kb.confirmed is None and kb.abandoned == 1
    n = len(port.log)
    assert kb.send_frame(frame)
    port.log = port.log[n:]
    assert _painted(port) == set(BY_ZONE)


def test_unacknowledged_frame_end_leaves_cache_uncertain() -> None:
    kb, port, _ = _keyboard()
    kb.claim(BASE_FRAME)
    port.faults[(PERKEY, 7)] = ["drop"]
    assert not kb.send_frame({**BASE_FRAME, BY_NAME["a"].zone: (1, 2, 3)})
    assert kb.confirmed is None


def test_three_abandoned_frames_request_reclaim() -> None:
    kb, port, _ = _keyboard()
    kb.claim(BASE_FRAME)
    for i in range(3):
        port.faults[(PERKEY, 1)] = ["error"]
        kb.send_frame({**BASE_FRAME, BY_NAME["a"].zone: (i, i, i + 1)})
    assert kb.needs_reclaim


def test_check_control_detects_takeover() -> None:
    kb, port, _ = _keyboard()
    kb.claim(BASE_FRAME)
    assert kb.check_control() and kb.confirmed is None       # periodic full repaint
    port.mode = 1                                           # something switched back to onboard
    assert not kb.check_control()


def test_check_control_without_onboard_reasserts_sw_control() -> None:
    kb, port, _ = _keyboard(features={0x8081: 0x10, 0x8071: 0x0F})
    kb.claim(BASE_FRAME)
    n = len(port.requests(EFFECTS, 5))
    assert kb.check_control()
    assert len(port.requests(EFFECTS, 5)) == n + 1 and kb.confirmed is None


def _connector(clock, ports):
    """A Connector over a list of fake ports, one per open; `present` toggles enumeration."""
    remaining = iter(ports)
    present = {"yes": True}

    def find():
        return b"/dev/hidraw2" if present["yes"] else None

    c = Connector(find=find, open_port=lambda path: next(remaining), clock=clock, sleep=clock.sleep)
    return c, present


def test_quarantine_survives_reclaim_and_resets_on_reenumeration() -> None:
    clock = FakeClock()
    ports = [FakeKeyboardPort(clock) for _ in range(3)]
    c, present = _connector(clock, ports)
    kb = c.connect(BASE_FRAME)
    ports[0].faults[(ONBOARD, 2)] = ["drop"]
    assert not kb.check_control()
    bad = set(c.quarantine)
    assert len(bad) == 1
    c.reclaim(BASE_FRAME)
    assert bad <= c.quarantine
    assert all((d[3] & 0x0F) not in bad for _, d in ports[1].writes)
    present["yes"] = False
    c.drop()
    with pytest.raises(DeviceGone):
        c.connect(BASE_FRAME)
    present["yes"] = True
    c.connect(BASE_FRAME)
    assert not c.quarantine


def test_stale_getfeature_reply_after_reopen_does_not_match_discovery() -> None:
    clock = FakeClock()
    ports = [FakeKeyboardPort(clock) for _ in range(2)]
    c, _ = _connector(clock, ports)
    c.connect(BASE_FRAME)
    c.quarantine.add(1)
    ports[1].schedule(0.0, ok_report(0x00, 0, 1, b"\x55"), counts=False)   # stale reply, quarantined id 1
    kb = c.reclaim(BASE_FRAME)
    assert kb.idx[0x8081] == 0x10


def test_io_error_counts_as_reenumeration() -> None:
    clock = FakeClock()
    ports = [FakeKeyboardPort(clock) for _ in range(2)]
    c, _ = _connector(clock, ports)
    c.connect(BASE_FRAME)
    c.quarantine.add(5)
    c.drop(DeviceGone("read failed", io_error=True))
    c.connect(BASE_FRAME)
    assert not c.quarantine
