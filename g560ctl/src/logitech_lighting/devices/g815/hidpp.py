"""HID++ 2.0 transport for the G815: request tracking, write pacing, fence, frame path.

Rules come from the spec's "Sending" section and the Gate A results:
- long reports only (0x11, device 0xFF, 20 bytes); errors are `11 ff ff <feat> <fn|sw> <code>`;
- an sw_id (1-15) is reusable only once a reply closes its entry; a request with no reply
  at all is quarantined for the life of the device connection (the caller carries the
  quarantine set across handle reopens);
- consecutive writes are spaced >= 1 ms apart (the G815 silently drops back-to-back writes);
- after any timeout, a root-feature ping fence clears late replies before the next request.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

LONG = 0x11
DEVICE = 0xFF
ERROR = 0xFF
BUSY = 0x08
REPORT_LEN = 20
SW_IDS = range(1, 16)

WRITE_GAP = 0.001             # Gate A: 0.5 ms still drops writes; never lower this
FRAME_TIMEOUT = 0.050         # per frame-path request, including frameEnd
CONTROL_TIMEOUT = 0.500       # per control request and per fence ping
FRAME_DEADLINE = 0.060        # from a frame's first write
CONTROL_BUSY_RETRIES = (0.030, 0.060, 0.090)
FRAME_END_RETRY = 0.003
FRAME_END_BUDGET = 0.150
BUSY_WAIT_CAP = 0.100
WINDOW_MAX = 4
WINDOW_MIN = 2
CLEAN_FRAMES_TO_GROW = 16
MIN_FREE_IDS = 3              # window 2 + the fence ping


class DeviceGone(Exception):
    """The keyboard cannot be talked to. io_error=True: the handle died (unplug)."""

    def __init__(self, reason: str, io_error: bool = False) -> None:
        super().__init__(reason)
        self.io_error = io_error


class RequestFailed(Exception):
    """A control request got an error reply, stayed BUSY, or timed out."""

    def __init__(self, reason: str, code: int | None = None) -> None:
        super().__init__(reason)
        self.code = code


class Port(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, timeout_ms: int) -> bytes: ...
    def close(self) -> None: ...


def build(feat: int, fn: int, sw: int, params: bytes = b"") -> bytes:
    if len(params) > 16:
        raise ValueError("HID++ long report params are at most 16 bytes")
    return bytes([LONG, DEVICE, feat, (fn << 4) | sw]) + bytes(params).ljust(16, b"\x00")


@dataclass(frozen=True)
class Reply:
    error: bool
    feat: int
    fn: int
    sw: int
    params: bytes   # 16 bytes for a success reply, empty for an error
    code: int = 0


def parse(report: bytes) -> Reply | None:
    """Decode a long report; anything else (short reports, NKRO input) is None."""
    if len(report) < REPORT_LEN or report[0] != LONG or report[1] != DEVICE:
        return None
    if report[2] == ERROR:
        return Reply(True, report[3], report[4] >> 4, report[4] & 0x0F, b"", report[5])
    return Reply(False, report[2], report[3] >> 4, report[3] & 0x0F, bytes(report[4:20]))


@dataclass
class _Entry:
    feat: int
    fn: int
    sw: int
    params: bytes
    echo: int               # echoed parameter prefix length that must match
    ping: int | None        # fence ping byte expected at reply params[2]
    deadline: float = 0.0

    def matches(self, r: Reply) -> bool:
        if (r.feat, r.fn, r.sw) != (self.feat, self.fn, self.sw):
            return False
        if r.error:
            return True
        if r.params[:self.echo] != self.params[:self.echo]:
            return False
        return self.ping is None or r.params[2] == self.ping


class Sender:
    def __init__(
        self,
        port: Port,
        quarantine: set[int] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.port = port
        self.quarantine = quarantine if quarantine is not None else set()
        self._clock = clock
        self._sleep = sleep
        self._open: dict[int, _Entry] = {}
        self._last_sw = 0
        self._last_write = float("-inf")
        self._ping = 0
        self.needs_fence = False
        self.window = WINDOW_MAX
        self._clean_frames = 0
        self._busy_per_zone = 0.0
        self.dropped = 0          # reports that matched no open entry

    # -- ids and raw I/O ---------------------------------------------------

    def free_ids(self) -> int:
        return sum(1 for i in SW_IDS if i not in self.quarantine and i not in self._open)

    def _alloc(self) -> int:
        for k in range(1, 16):
            sw = (self._last_sw + k - 1) % 15 + 1
            if sw not in self.quarantine and sw not in self._open:
                self._last_sw = sw
                return sw
        raise DeviceGone("no free HID++ software ids")

    def _write(self, report: bytes) -> None:
        wait = self._last_write + WRITE_GAP - self._clock()
        if wait > 0:
            self._sleep(wait)
        try:
            n = self.port.write(report)
        except OSError as exc:
            raise DeviceGone(f"write failed: {exc}", io_error=True) from exc
        self._last_write = self._clock()
        if n is not None and n < 0:
            raise DeviceGone("write returned -1", io_error=True)

    def _read(self, timeout: float) -> Reply | None:
        try:
            data = self.port.read(max(1, int(timeout * 1000)))
        except OSError as exc:
            raise DeviceGone(f"read failed: {exc}", io_error=True) from exc
        if not data:
            return None
        reply = parse(bytes(data))
        if reply is None:
            self.dropped += 1
        return reply

    def _send(self, feat: int, fn: int, params: bytes, timeout: float,
              echo: int = 0, ping: int | None = None) -> _Entry:
        entry = _Entry(feat, fn, self._alloc(), bytes(params), echo, ping)
        self._open[entry.sw] = entry
        self._write(build(feat, fn, entry.sw, entry.params))
        entry.deadline = self._clock() + timeout
        return entry

    def _dispatch(self, r: Reply) -> _Entry | None:
        for entry in self._open.values():
            if entry.matches(r):
                del self._open[entry.sw]
                return entry
        self.dropped += 1
        return None

    def _expire(self) -> list[_Entry]:
        now = self._clock()
        gone = [e for e in self._open.values() if e.deadline <= now]
        for entry in gone:
            del self._open[entry.sw]
            self.quarantine.add(entry.sw)
            self.needs_fence = True
        return gone

    def _await(self, entry: _Entry) -> Reply | None:
        while True:
            left = entry.deadline - self._clock()
            if left <= 0:
                self._expire()
                return None
            r = self._read(left)
            if r is not None and self._dispatch(r) is entry:
                return r

    # -- fence and control path --------------------------------------------

    def fence(self) -> None:
        """Ping until its echoed byte returns; everything before it is discarded."""
        end = self._clock() + CONTROL_TIMEOUT
        while self._clock() < end:
            self._ping = self._ping % 255 + 1
            entry = self._send(0x00, 1, bytes([0, 0, self._ping]), end - self._clock(), ping=self._ping)
            r = self._await(entry)
            if r is None:
                break
            if not r.error:
                self.needs_fence = False
                return
            self._sleep(CONTROL_BUSY_RETRIES[0])
        raise DeviceGone("ping fence timed out")

    def request(self, feat: int, fn: int, params: bytes = b"") -> bytes:
        """Control path: one request at a time; BUSY retried after 30/60/90 ms. Returns reply params."""
        for delay in (*CONTROL_BUSY_RETRIES, None):
            if self.needs_fence:
                self.fence()
            entry = self._send(feat, fn, params, CONTROL_TIMEOUT)
            r = self._await(entry)
            if r is None:
                self.fence()
                raise RequestFailed("timeout")
            if not r.error:
                return r.params
            if r.code != BUSY or delay is None:
                raise RequestFailed(f"error {r.code:#04x}", r.code)
            self._sleep(delay)
        raise AssertionError("unreachable")

    # -- frame path ----------------------------------------------------------

    def send_writes(self, feat: int, writes: list[tuple[int, bytes]], echo: dict[int, int]) -> bool:
        """Pipelined per-key writes. True only if every write was acknowledged OK."""
        if self.needs_fence:
            self.fence()
        free = self.free_ids()
        if free < MIN_FREE_IDS:
            raise DeviceGone(f"only {free} HID++ software ids left")
        window = min(self.window, free - 1)
        queue = list(writes)
        ok, lost = True, False
        start = self._clock()
        while self._open or (ok and queue):
            while ok and queue and len(self._open) < window:
                fn, params = queue.pop(0)
                self._send(feat, fn, params, FRAME_TIMEOUT, echo.get(fn, 0))
            if self._clock() - start > FRAME_DEADLINE:
                ok = False
            if self._expire():
                ok, lost = False, True
            if not self._open:
                continue
            wait = min(e.deadline for e in self._open.values()) - self._clock()
            r = self._read(max(wait, 0.001))
            if r is not None and self._dispatch(r) is not None and r.error:
                ok = False
        self._adapt(lost)
        return ok

    def _adapt(self, lost: bool) -> None:
        if lost:
            self.window = max(WINDOW_MIN, self.window // 2)
            self._clean_frames = 0
            return
        self._clean_frames += 1
        if self._clean_frames >= CLEAN_FRAMES_TO_GROW and self.window < WINDOW_MAX:
            self.window += 1
            self._clean_frames = 0

    def frame_end(self, feat: int, zones: int, fn: int = 7) -> bool:
        """frameEnd; BUSY is backpressure. True once acknowledged."""
        start = self._clock()
        first_busy: float | None = None
        while self._clock() - start < FRAME_END_BUDGET:
            if self.needs_fence:
                self.fence()
            r = self._await(self._send(feat, fn, b"\x00", FRAME_TIMEOUT))
            if r is None:
                return False
            if not r.error:
                if first_busy is not None and zones:
                    per_zone = (self._clock() - first_busy) / zones
                    self._busy_per_zone = per_zone if not self._busy_per_zone else (
                        0.8 * self._busy_per_zone + 0.2 * per_zone)
                return True
            if r.code != BUSY:
                return False
            if first_busy is None:
                first_busy = self._clock()
                self._sleep(min(BUSY_WAIT_CAP, self._busy_per_zone * zones))
            else:
                self._sleep(FRAME_END_RETRY)
        return False
