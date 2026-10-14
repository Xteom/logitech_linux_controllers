import pytest

from g815_fakes import FakeClock, FakeKeyboardPort, ok_report
from logitech_lighting.devices.g815.hidpp import (
    CONTROL_BUSY_RETRIES, WINDOW_MAX, WINDOW_MIN, DeviceGone, RequestFailed, Sender, build, parse,
)

PK = 0x10
ECHO = {1: 1, 5: 1, 6: 4}


def _sender(**port_kw):
    clock = FakeClock()
    port = FakeKeyboardPort(clock, **port_kw)
    return Sender(port, clock=clock, sleep=clock.sleep), port, clock


def _writes(n: int) -> list[tuple[int, bytes]]:
    return [(1, bytes([z, z, z, z])) for z in range(1, n + 1)]


def test_build_and_parse_round_trip() -> None:
    report = build(0x10, 5, 3, bytes([1, 3, 255, 0, 0]))
    assert report[:4] == bytes([0x11, 0xFF, 0x10, 0x53]) and len(report) == 20
    r = parse(ok_report(0x10, 5, 3, b"\x01"))
    assert (r.error, r.feat, r.fn, r.sw, r.params[0]) == (False, 0x10, 5, 3, 1)
    e = parse(bytes([0x11, 0xFF, 0xFF, 0x10, 0x53, 0x08]).ljust(20, b"\x00"))
    assert (e.error, e.feat, e.fn, e.sw, e.code) == (True, 0x10, 5, 3, 0x08)
    assert parse(b"\x10\xff\x00\x00\x00\x00\x00") is None        # short report
    assert parse(bytes(20)) is None                                # not HID++


def test_open_ids_never_reused_across_wraparound() -> None:
    s, _, _ = _sender()
    entries = [s._send(PK, 1, b"\x01", 1.0) for _ in range(15)]
    assert len({e.sw for e in entries}) == 15
    with pytest.raises(DeviceGone):
        s._send(PK, 1, b"\x01", 1.0)


def test_control_request_returns_data_on_header_match() -> None:
    s, _, _ = _sender()
    assert s.request(0x00, 0, (0x8081).to_bytes(2, "big"))[0] == 0x10   # getFeature payload is data
    assert s.request(PK, 0, bytes([0, 1, 0]))[1] == 1                     # zone discovery page 1


def test_error_reply_matches_on_bytes_3_4() -> None:
    s, port, _ = _sender()
    port.faults[(PK, 0)] = ["error"]
    with pytest.raises(RequestFailed) as exc:
        s.request(PK, 0, bytes([0, 0, 0]))
    assert exc.value.code == 0x05
    assert not s.quarantine


def test_control_busy_retried_after_30_60_90_ms() -> None:
    s, port, _ = _sender()
    port.faults[(0x11, 2)] = ["busy", "busy", "busy"]
    assert s.request(0x11, 2)[0] == 0x01
    times = [t for t, d in port.writes if d[2] == 0x11]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(gaps) == 3
    assert all(g >= want for g, want in zip(gaps, CONTROL_BUSY_RETRIES))


def test_control_busy_four_times_fails() -> None:
    s, port, _ = _sender()
    port.faults[(0x11, 2)] = ["busy"] * 4
    with pytest.raises(RequestFailed) as exc:
        s.request(0x11, 2)
    assert exc.value.code == 0x08


def test_late_reply_after_timeout_is_discarded_by_fence() -> None:
    s, port, _ = _sender()
    port.faults[(0x00, 0)] = [("late", 0.7)]                 # getFeature(0x8081) answers 0x10, late
    with pytest.raises(RequestFailed):
        s.request(0x00, 0, (0x8081).to_bytes(2, "big"))
    assert len(s.quarantine) == 1
    assert s.request(0x00, 0, (0x8100).to_bytes(2, "big"))[0] == 0x11   # not the stale 0x10


def test_reply_after_fence_for_quarantined_id_is_dropped() -> None:
    s, port, _ = _sender()
    port.faults[(0x00, 0)] = [("late", 1.5)]
    with pytest.raises(RequestFailed):
        s.request(0x00, 0, (0x8081).to_bytes(2, "big"))      # fence completes at ~0.5 s
    bad = next(iter(s.quarantine))
    dropped = s.dropped
    port.clock.sleep(1.2)                                    # the stale reply is now due
    assert s.request(0x00, 0, (0x8100).to_bytes(2, "big"))[0] == 0x11
    assert s.dropped == dropped + 1 and bad in s.quarantine


def test_ping_timeout_means_device_gone() -> None:
    s, port, _ = _sender()
    s.needs_fence = True
    port.faults[(0x00, 1)] = ["drop"]
    with pytest.raises(DeviceGone):
        s.request(PK, 0, bytes([0, 0, 0]))


def test_ping_with_wrong_echo_byte_does_not_complete_fence() -> None:
    s, port, _ = _sender()
    s.needs_fence = True
    port.faults[(0x00, 1)] = [("reply", lambda sw: ok_report(0x00, 1, sw, bytes([4, 2, 0xEE])))]
    port.faults[(0x00, 1)] += ["drop"] * 20
    with pytest.raises(DeviceGone):
        s.fence()


def test_writes_are_at_least_1ms_apart() -> None:
    s, port, _ = _sender()
    assert s.send_writes(PK, _writes(12), ECHO)
    times = [t for t, _ in port.writes]
    assert all(b - a >= 0.001 - 1e-9 for a, b in zip(times, times[1:]))


def test_out_of_order_replies_within_window() -> None:
    s, port, _ = _sender()
    port.faults[(PK, 1)] = [("late", 0.010)]
    assert s.send_writes(PK, _writes(4), ECHO)
    assert not s.quarantine


def test_wrong_echoed_payload_is_ignored() -> None:
    s, port, _ = _sender()
    port.faults[(PK, 1)] = [("reply", lambda sw: ok_report(PK, 1, sw, b"\x63"))]   # echoes zone 0x63, sent 0x01
    assert not s.send_writes(PK, _writes(1), ECHO)
    assert len(s.quarantine) == 1


def test_busy_write_frees_id_but_missing_reply_quarantines() -> None:
    s, port, _ = _sender()
    port.faults[(PK, 1)] = ["busy"]
    assert not s.send_writes(PK, _writes(3), ECHO)
    assert not s.quarantine
    port.faults[(PK, 1)] = ["drop"]
    assert not s.send_writes(PK, _writes(3), ECHO)
    assert len(s.quarantine) == 1


def test_window_never_exceeds_4_in_flight() -> None:
    s, port, _ = _sender(latency=0.005)
    assert s.send_writes(PK, _writes(10), ECHO)
    assert port.max_outstanding == WINDOW_MAX


def test_window_halves_on_lost_reply_and_grows_back() -> None:
    s, port, _ = _sender()
    port.faults[(PK, 1)] = ["drop"]
    s.send_writes(PK, _writes(2), ECHO)
    assert s.window == WINDOW_MIN
    for _ in range(16):
        assert s.send_writes(PK, _writes(2), ECHO)
    assert s.window == WINDOW_MIN + 1
    for _ in range(64):
        s.send_writes(PK, _writes(2), ECHO)
    assert s.window == WINDOW_MAX


def test_few_free_ids_shrink_window_then_stop() -> None:
    s, port, _ = _sender(latency=0.005)
    s.quarantine.update(range(1, 13))                        # 3 ids left: window 2 + fence
    assert s.send_writes(PK, _writes(6), ECHO)
    assert port.max_outstanding == 2
    s.quarantine.add(13)                                     # 2 ids left
    with pytest.raises(DeviceGone):
        s.send_writes(PK, _writes(1), ECHO)


def test_frame_end_busy_is_retried_until_acknowledged() -> None:
    s, port, _ = _sender()
    port.faults[(PK, 7)] = ["busy", "busy"]
    assert s.frame_end(PK, zones=20)
    assert len(port.requests(PK, 7)) == 3


def test_frame_end_never_acknowledged_is_false() -> None:
    s, port, _ = _sender()
    port.faults[(PK, 7)] = ["drop"]
    assert not s.frame_end(PK, zones=20)


def test_oserror_and_minus_one_mean_device_gone() -> None:
    s, port, _ = _sender()
    port.fail_io = True
    with pytest.raises(DeviceGone) as exc:
        s.request(PK, 0, bytes([0, 0, 0]))
    assert exc.value.io_error
    s, port, _ = _sender()
    port.write_result = -1
    with pytest.raises(DeviceGone) as exc:
        s.send_writes(PK, _writes(1), ECHO)
    assert exc.value.io_error


def test_notifications_go_to_handler_not_dropped() -> None:
    from g815_fakes import notify_report

    s, port, _ = _sender()
    seen = []
    s.on_notify = seen.append
    port.schedule(0.0, notify_report(0x0A, b"\x04"), counts=False)
    assert s.request(0x00, 0, (0x8081).to_bytes(2, "big"))[0] == 0x10
    assert [(r.feat, r.params[0]) for r in seen] == [(0x0A, 0x04)]
    assert s.dropped == 0


def test_poll_reads_notifications_while_idle() -> None:
    from g815_fakes import notify_report

    s, port, _ = _sender()
    seen = []
    s.on_notify = seen.append
    port.schedule(0.0, notify_report(0x0A, b"\x01"), counts=False)
    port.schedule(0.0, notify_report(0x0A, b"\x00"), counts=False)
    s.poll()
    assert [r.params[0] for r in seen] == [0x01, 0x00]
