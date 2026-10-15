"""Test doubles for the G815 transport: a fake clock and a fake keyboard port.

FakeKeyboardPort answers like the real G815 did in Gate A (feature indexes, echo
prefixes, zone bitmap, ping echo, onboard mode and profile). `faults[(feat, fn)]` is
a list consumed one entry per request to that (feature index, function):
  "drop"            no reply at all
  "busy" / "error"  error reply 0x08 / 0x05
  ("late", s)       the normal reply, delayed by s seconds
  ("reply", f)      f(sw) -> 20-byte report sent instead of the normal reply
  ("stall", s)      the normal reply, but the next read starts s seconds late (the host
                    process was descheduled while the reply sat in the hidraw buffer)
"""
from __future__ import annotations

import heapq

from logitech_lighting.devices.g815.layout import KEYS, PHASE1_VALID_ZONES

FEATURES = {0x8081: 0x10, 0x8071: 0x0F, 0x8100: 0x11, 0x8010: 0x0A}   # as on the real G815
PERKEY, EFFECTS, ONBOARD, GKEY = 0x10, 0x0F, 0x11, 0x0A
DEVICE_ZONES = frozenset(PHASE1_VALID_ZONES) | {0x00}   # Gate A: zone 0 is reported too


def ok_report(feat: int, fn: int, sw: int, params: bytes = b"") -> bytes:
    return bytes([0x11, 0xFF, feat, (fn << 4) | sw]) + bytes(params).ljust(16, b"\x00")


def notify_report(feat: int, params: bytes) -> bytes:
    """A device notification: function 0, software id 0 (e.g. G-key bitmask from 0x8010)."""
    return ok_report(feat, 0, 0, params)


def err_report(feat: int, fn: int, sw: int, code: int) -> bytes:
    return bytes([0x11, 0xFF, 0xFF, feat, (fn << 4) | sw, code]).ljust(20, b"\x00")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.0)


class FakeKeyboardPort:
    def __init__(self, clock: FakeClock, features: dict[int, int] | None = None,
                 zones: frozenset[int] = DEVICE_ZONES, latency: float = 0.0005) -> None:
        self.clock = clock
        self.features = dict(FEATURES if features is None else features)
        self.zones = zones
        self.latency = latency
        self.faults: dict[tuple[int, int], list] = {}
        self.writes: list[tuple[float, bytes]] = []
        self.log: list[tuple[int, int, bytes]] = []     # (feat, fn, params) per request
        self.mode = 0x01
        self.profile = b"\x00\x01"
        self.profile_selects = 0
        self.closed = False
        self.fail_io = False
        self.write_result: int | None = None
        self.outstanding = 0
        self.max_outstanding = 0
        self._queue: list[tuple[float, int, bytes, bool]] = []
        self._seq = 0
        self._stall = 0.0

    def schedule(self, delay: float, report: bytes, counts: bool = True) -> None:
        heapq.heappush(self._queue, (self.clock() + delay, self._seq, bytes(report), counts))
        self._seq += 1

    def requests(self, feat: int | None = None, fn: int | None = None) -> list[bytes]:
        return [p for f, n, p in self.log if (feat is None or f == feat) and (fn is None or n == fn)]

    def write(self, data: bytes) -> int:
        if self.fail_io:
            raise OSError(19, "No such device")
        if self.write_result is not None:
            return self.write_result
        data = bytes(data)
        self.writes.append((self.clock(), data))
        feat, fn, sw, params = data[2], data[3] >> 4, data[3] & 0x0F, data[4:20]
        self.log.append((feat, fn, params))
        pending = self.faults.get((feat, fn))
        action = pending.pop(0) if pending else None
        self.outstanding += 1
        self.max_outstanding = max(self.max_outstanding, self.outstanding)
        if action == "drop":
            self.outstanding -= 1
            return len(data)
        if action in ("busy", "error"):
            self.schedule(self.latency, err_report(feat, fn, sw, 0x08 if action == "busy" else 0x05))
            return len(data)
        if isinstance(action, tuple) and action[0] == "stall":
            self._stall += action[1]
            action = None
        if isinstance(action, tuple) and action[0] == "reply":
            self.schedule(self.latency, action[1](sw))
            return len(data)
        delay = action[1] if isinstance(action, tuple) and action[0] == "late" else self.latency
        self.schedule(delay, ok_report(feat, fn, sw, self._answer(feat, fn, params)))
        return len(data)

    def _answer(self, feat: int, fn: int, params: bytes) -> bytes:
        if feat == 0x00 and fn == 0:                       # root getFeature
            return bytes([self.features.get(int.from_bytes(params[:2], "big"), 0)])
        if feat == 0x00 and fn == 1:                       # root getProtocolVersion (ping)
            return bytes([4, 2, params[2]])
        fid = {idx: f for f, idx in self.features.items()}.get(feat)
        if fid == 0x8081:
            if fn == 0:
                page = params[1]
                bitmap = bytearray(14)
                for z in self.zones:
                    if z // 112 == page:
                        bitmap[(z % 112) // 8] |= 1 << (z % 8)
                return bytes([0, page]) + bytes(bitmap)
            if fn in (1, 5):
                return params[:1]
            if fn == 6:
                return params[:4]
            return b""
        if fid == 0x8100:
            if fn == 1:
                self.mode = params[0]
            elif fn == 2:
                return bytes([self.mode])
            elif fn == 3:
                self.profile = params[:2]
                self.profile_selects += 1
            elif fn == 4:
                return self.profile
        return b""

    def read(self, timeout_ms: int) -> bytes:
        if self.fail_io:
            raise OSError(19, "No such device")
        self.clock.now += self._stall
        self._stall = 0.0
        if self._queue and self._queue[0][0] <= self.clock() + timeout_ms / 1000:
            t, _, report, counts = heapq.heappop(self._queue)
            self.clock.now = max(self.clock.now, t)
            if counts:
                self.outstanding -= 1
            return report
        self.clock.now += timeout_ms / 1000
        return b""

    def close(self) -> None:
        self.closed = True


# -- daemon doubles (a claimed keyboard, the connector, the X key source) --

class FakeKb:
    def __init__(self) -> None:
        self.valid = frozenset(k.zone for k in KEYS)
        self.frames: list[dict] = []
        self.committed = 0
        self.released = 0
        self.control_ok = True
        self.needs_reclaim = False
        self.fail: Exception | None = None
        self.gkeys: list[str] = []

    def send_frame(self, frame, resync=()):
        if self.fail:
            raise self.fail
        if not self.frames or self.frames[-1] != frame:
            self.committed += 1
        self.frames.append(frame)
        return True

    def poll_keys(self):
        if self.fail:
            raise self.fail
        out, self.gkeys = self.gkeys, []
        return out

    def check_control(self):
        return self.control_ok

    def release(self):
        self.released += 1


class FakeConnector:
    def __init__(self) -> None:
        self.kb = FakeKb()
        self.connects = 0
        self.reclaims = 0
        self.drops: list = []
        self.error: Exception | None = None

    def connect(self, frame):
        self.connects += 1
        if self.error:
            raise self.error
        self.kb.frames.append(frame)
        return self.kb

    def reclaim(self, frame):
        self.reclaims += 1
        return self.connect(frame)

    def drop(self, error=None):
        self.drops.append(error)


class FakeKeys:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.raise_on_poll: Exception | None = None

    def poll(self):
        if self.raise_on_poll:
            raise self.raise_on_poll
        out, self.pending = self.pending, []
        return out
