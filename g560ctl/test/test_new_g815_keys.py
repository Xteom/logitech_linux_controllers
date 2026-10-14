import struct

from g815_fakes import FakeClock
from logitech_lighting.devices.g815.keys import HIERARCHY_SETTLE, KeyFilter, RawKey, decode_raw


def _raw_event_body(deviceid: int, time: int, keycode: int, sourceid: int) -> bytes:
    # XI2 RawKeyPress after the 10-byte GE header: deviceid, time, detail, sourceid,
    # valuators_len, flags, pad (client byte order), as python-xlib leaves it in ev.data.
    return struct.pack("=HIIHHI4x", deviceid, time, keycode, sourceid, 0, 0)


def test_decode_raw_event_body() -> None:
    raw = decode_raw(_raw_event_body(3, 123456, 38, 16))
    assert raw == RawKey(deviceid=3, time=123456, detail=38, sourceid=16)


def test_filter_accepts_only_g815_sources() -> None:
    f = KeyFilter(lambda: {15, 16})
    assert f.key_name(RawKey(3, 0, 38, 16)) == "a"          # X keycode 38 = evdev 30 = KEY_A
    assert f.key_name(RawKey(3, 0, 38, 12)) is None          # another keyboard


def test_unmapped_keycode_is_ignored() -> None:
    f = KeyFilter(lambda: {15})
    assert f.key_name(RawKey(3, 0, 8 + 240, 15)) is None


def test_hierarchy_burst_requeries_once_after_settling() -> None:
    clock = FakeClock()
    answers = iter([{15, 16}, {21, 22}])
    calls = []

    def query():
        calls.append(clock())
        return next(answers)

    f = KeyFilter(query, clock=clock)
    for _ in range(16):
        f.hierarchy_changed()
        clock.sleep(0.01)
        f.tick()
    assert len(calls) == 1                                   # still settling
    clock.sleep(HIERARCHY_SETTLE)
    f.tick()
    assert len(calls) == 2 and f.ids == {21, 22}
    assert f.key_name(RawKey(3, 0, 38, 21)) == "a"
