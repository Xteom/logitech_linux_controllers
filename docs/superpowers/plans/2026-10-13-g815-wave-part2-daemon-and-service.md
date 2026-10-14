# G815 Wave — Part 2: Transport, Daemon, CLI and Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Part 1 effect modules into a running feature: a HID++ transport and keyboard driver, the XI2 key source, the daemon (state machine, control socket, lock-screen pause, reconnect), the `wave` CLI subcommand, and a systemd user service, so `ligths wave red|blue|off|status` works from login.

**Architecture:** New modules in `logitech_lighting/devices/g815/`:
- **`hidpp.py`:** the transport (sw_id tracking, quarantine, 1 ms write pacing, ping fence, pipelined frame path).
- **`keyboard.py`:** G815 semantics (claim, release, frames, control check) plus `Connector` (open, reopen, quarantine carry-over).
- **`state.py`:** the pure state machine.
- **`keys.py`:** XI2 raw key presses.
- **`daemon.py`:** the frame loop, socket server and `run_daemon`.
- **`wave_cli.py`:** the socket client used by `cli.py`.

Every module that talks to hardware or X takes injectable collaborators, so all logic is tested with fakes (`g560ctl/test/g815_fakes.py`). The last task installs the service and runs the hardware checks with the user.

**Tech Stack:** Python 3.10 (`g560ctl/.venv`), pytest, `hidapi` 0.15 (`import hidraw`), `python-xlib` 0.33, systemd user units, GNOME `gdbus`.

**Spec:** `docs/superpowers/specs/2026-10-13-g815-wave-design.md`. Read its "Sending", "Lifecycle and failure handling", "Gate A results" and "Gate B results" sections. Part 1 plan: `docs/superpowers/plans/2026-10-13-g815-wave-part1-effect-and-gates.md` (Tasks 1-6 done; `layout`, `presets`, `ripple`, `frame` exist and are tested).

**How this plan was validated:**
- Every code block below was run, task by task, in a scratch worktree. The full suite went 59 → 146 passing.
- Each new test file was confirmed to fail before its implementation existed.
- The two Review Focus fixes were mutation-checked: their tests fail when the fix is removed.
- `Connector` + `HidrawPort` + `Keyboard` were run against the real G815. The claim took 26 ms, then 40 committed fps with 8 rings at 12 presses/s, `check_control` read host mode, and the release was clean.
- `XKeySource` was run against the live X server. An `xdotool key a` arrived from XTEST device 5, decoded as keycode 38, and was rejected. This closes Gate B's "other-device rejection not observed".

## Global Constraints

- **Device:** G815 `046d:c33f`.
  - HID++ node: the hidapi `hidraw` entry with usage page `0xFF43`, usage `0x0602`.
  - Long reports only: `0x11`, device `0xFF`, 20 bytes.
  - Error replies: `11 ff ff <feat> <fn|sw> <code>`; BUSY = `0x08`.
- **Never `import hid`.** It is hidapi's libusb backend and would detach the keyboard driver. Always use `import hidraw`.
- **Claim (Gate A), in this order:**
  1. root getFeature for `0x8081`, `0x8071`, `0x8100`;
  2. `0x8071` fn5 `[01 03 04]`;
  3. `0x8100` fn1 `[02]`;
  4. `0x8081` fn0 `[00 page 00]` for pages 0-2 (bitmap `params[2:16]`, `zone = page*112 + byte*8 + bit`);
  5. full base frame + frameEnd (fn7 `[00]`), all acknowledged.
- **Release (Gate A), in this order:**
  1. `0x8071` fn5 `[01 00 00]`;
  2. `0x8100` fn1 `[01]`;
  3. `0x8100` fn4 (getCurrentProfile, reply bytes 0-1);
  4. `0x8100` fn3 with those 2 bytes. Without the re-select, the last host frame stays on the keys.
- **Zones:** paint only zones the keyboard reports **and** `layout.py` has. Zone `0x00` is reported, but has no LED.
- **Echo prefixes (Gate A):** fn1 and fn5 echo params byte 0; fn6 echoes bytes 0-3. Data replies (getFeature, zone discovery, getOnboardMode, getCurrentProfile) match on the header only. The ping (root fn1 `[00 00 ping]`) echoes `ping` at params[2].
- **Pacing:** consecutive writes are ≥ **1 ms** apart (back-to-back writes are silently dropped; 0.5 ms still drops). Never lower `WRITE_GAP`.
- **Window:** start at 4. Halve (min 2) on a lost reply; +1 after 16 clean frames, up to 4. The window is also at most free ids − 1; below 3 free ids → `DeviceGone`.
- **Timeouts:**
  - Frame-path requests (including frameEnd): 50 ms. Control requests and the fence ping: 500 ms.
  - Only a request with **no reply at all** quarantines its sw_id. A BUSY reply frees it.
  - Quarantine survives re-claims and reopens. It resets only on re-enumeration: the device seen absent, or its handle dying with an I/O error.
- **Frame:**
  - 60 ms deadline from the first write.
  - frameEnd only after every write is acknowledged.
  - BUSY on frameEnd: retry every 3 ms for up to 150 ms, after an initial learned wait (≤ 100 ms).
  - Any failure → cache uncertain → the next frame is a full repaint.
  - 3 abandoned frames in a row → re-claim.
- **Control path:** BUSY retried after 30/60/90 ms, then fail.
- **Lifecycle:**
  - States OFF / DISCONNECTED / LOCKED / ACTIVE (spec table). OFF is sticky. An unknown lock state counts as LOCKED.
  - Lock poll: 1 s via `/usr/bin/gdbus … org.gnome.ScreenSaver.GetActive`, 500 ms timeout.
  - Control check every 10 s. Reconnect poll every 2 s. Claim backoff 2/4/8/16/30 s.
- **Files:**
  - State file `~/.config/logitech-lighting/wave.json`, holding `{"preset", "off"}`.
  - Socket `$XDG_RUNTIME_DIR/g815-wave.sock`, mode 0600, one JSON line per request and per reply.
  - Lock `$XDG_RUNTIME_DIR/g815-wave.lock` (`flock`, held for the daemon's lifetime).
- **CLI:**
  - `wave red|blue|off|status|daemon`, dispatched before any G560 code runs.
  - With no daemon running: `wave daemon not running — start it with: systemctl --user start g815-wave`, exit 1.
- **Exit codes:**
  - Missing `DISPLAY`/`XAUTHORITY` → exit 0, with the hint `systemctl --user import-environment DISPLAY XAUTHORITY`.
  - X connection loss → release, exit 0.
  - Already running → exit 1.
- **Privacy:** key presses live only in memory as ring origins. Never log key names or keycodes, except one debug line per unmapped keycode number.
- **Tests:** `g560ctl/test/test_new_g815_*.py`, with shared doubles in `g560ctl/test/g815_fakes.py`. Suite command: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`. The 59 Part 1 tests must stay green.
- **Do not touch:**
  - the G560 path;
  - `DeviceConfig` / `UnifiedController`;
  - the dead `g560ctl/*` modules;
  - `experiments/`.

## Review Focus

1. **`wave red` right after `wave off`, while a claim backoff is pending,** must reconnect at once, not after up to 30 s. *(Task 5 `test_leaving_off_connects_immediately`.)*
2. **An unwritable state file** (read-only `~/.config`, disk full) must not kill the daemon. The command still applies and the error is logged. *(Task 5 `test_unwritable_state_file_keeps_running`.)*
3. **A key pressed in the same tick the screen locks** must not start a ring. *(Task 5 `test_press_on_lock_tick_does_not_ring`.)*
4. **A re-claim that fails while ACTIVE** must land in DISCONNECTED with backoff and recover, not loop or crash. *(Task 5 `test_failed_reclaim_goes_disconnected_and_retries`.)*
5. **A garbage line on the control socket** gets `{"ok": false}`, and the daemon keeps serving. *(Task 6 `test_garbage_request_gets_error_reply`.)*

---

### Task 1: `hidpp.py` — HID++ transport

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/hidpp.py`
- Create: `g560ctl/test/g815_fakes.py` (fake clock + fake G815 port; Task 5 appends the daemon doubles)
- Test: `g560ctl/test/test_new_g815_hidpp.py`

**Interfaces:**
- **Produces:**
  - Exceptions:
    - `DeviceGone(reason, io_error=False)`, with an `.io_error: bool` attribute;
    - `RequestFailed(reason, code=None)`, with a `.code` attribute.
  - `Port` protocol: `write(bytes) -> int`, `read(timeout_ms) -> bytes`, `close()`.
  - `build(feat, fn, sw, params=b"") -> bytes`.
  - `parse(report) -> Reply | None`. `Reply` has `error`, `feat`, `fn`, `sw`, `params`, `code`.
  - `Sender(port, quarantine: set[int] | None = None, clock=time.monotonic, sleep=time.sleep)`:
    - methods:
      - `.request(feat, fn, params=b"") -> bytes` (the control path; returns reply params);
      - `.send_writes(feat, writes: list[tuple[int, bytes]], echo: dict[int, int]) -> bool`;
      - `.frame_end(feat, zones: int, fn=7) -> bool`;
      - `.fence()`;
      - `.free_ids() -> int`.
    - attributes: `.quarantine: set[int]`, `.window: int`, `.needs_fence: bool`, `.dropped: int`.
  - Constants: `WRITE_GAP`, `FRAME_TIMEOUT`, `CONTROL_TIMEOUT`, `FRAME_DEADLINE`, `CONTROL_BUSY_RETRIES`, `WINDOW_MAX`, `WINDOW_MIN`, `MIN_FREE_IDS`.
  - Test doubles in `g815_fakes`:
    - `FakeClock()`: callable; has `.now` and `.sleep(s)`.
    - `FakeKeyboardPort(clock, features=None, zones=DEVICE_ZONES, latency=0.0005)`:
      - attributes: `.faults[(feat, fn)]`, `.writes`, `.log`, `.mode`, `.profile`, `.profile_selects`, `.fail_io`, `.write_result`, `.max_outstanding`;
      - methods: `.schedule(delay, report, counts=True)`, `.requests(feat, fn)`.
    - `ok_report(...)`, `err_report(...)`.
    - Constants `PERKEY = 0x10`, `EFFECTS = 0x0F`, `ONBOARD = 0x11`.

- [ ] **Step 1: Write the fake device**

`g560ctl/test/g815_fakes.py`:

```python
"""Test doubles for the G815 transport: a fake clock and a fake keyboard port.

FakeKeyboardPort answers like the real G815 did in Gate A (feature indexes, echo
prefixes, zone bitmap, ping echo, onboard mode and profile). `faults[(feat, fn)]` is
a list consumed one entry per request to that (feature index, function):
  "drop"            no reply at all
  "busy" / "error"  error reply 0x08 / 0x05
  ("late", s)       the normal reply, delayed by s seconds
  ("reply", f)      f(sw) -> 20-byte report sent instead of the normal reply
"""
from __future__ import annotations

import heapq

from logitech_lighting.devices.g815.layout import PHASE1_VALID_ZONES

FEATURES = {0x8081: 0x10, 0x8071: 0x0F, 0x8100: 0x11}
PERKEY, EFFECTS, ONBOARD = 0x10, 0x0F, 0x11
DEVICE_ZONES = frozenset(PHASE1_VALID_ZONES) | {0x00}   # Gate A: zone 0 is reported too


def ok_report(feat: int, fn: int, sw: int, params: bytes = b"") -> bytes:
    return bytes([0x11, 0xFF, feat, (fn << 4) | sw]) + bytes(params).ljust(16, b"\x00")


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
```

- [ ] **Step 2: Write the failing tests**

`g560ctl/test/test_new_g815_hidpp.py`:

```python
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
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_hidpp.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'logitech_lighting.devices.g815.hidpp'`

- [ ] **Step 4: Write the implementation**

`g560ctl/src/logitech_lighting/devices/g815/hidpp.py`:

```python
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
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_hidpp.py -q`
Expected: `20 passed`

- [ ] **Step 6: Run the full suite and commit**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `79 passed`

```bash
git add g560ctl/src/logitech_lighting/devices/g815/hidpp.py g560ctl/test/g815_fakes.py g560ctl/test/test_new_g815_hidpp.py
git commit -m "feat(g815): HID++ transport with quarantine, write pacing and ping fence"
```

---

### Task 2: `keyboard.py` — claim, release, frames, connector

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/keyboard.py`
- Modify: `g560ctl/pyproject.toml` (add `hidapi>=0.14`)
- Test: `g560ctl/test/test_new_g815_keyboard.py`

**Interfaces:**
- **Consumes:**
  - `Sender`, `DeviceGone`, `RequestFailed`, `Port` (Task 1);
  - `encode`, `Write`, `FN_SET_RANGE`, `FN_SET_INDIVIDUAL` (Part 1 `frame.py`);
  - `BY_ZONE` (Part 1 `layout.py`).
- **Produces:**
  - `ClaimError`.
  - `parse_zone_page(page, params) -> set[int]`.
  - `usable_zones(discovered) -> frozenset[int]`.
  - `Keyboard(sender)`:
    - attributes:
      - `.idx: dict[int, int]`;
      - `.applied: set[str]`, containing `"sw"` and/or `"host"`;
      - `.valid: frozenset[int]`;
      - `.confirmed: dict | None`;
      - `.abandoned: int`;
      - `.committed: int`;
      - `.needs_reclaim: bool`.
    - methods:
      - `.claim(frame)`;
      - `.release()`;
      - `.send_frame(frame, resync=()) -> bool`;
      - `.check_control() -> bool`.
  - `find_path()` and `HidrawPort(path)`.
  - `Connector(find=find_path, open_port=HidrawPort, clock=time.monotonic, sleep=time.sleep)`:
    - attributes: `.quarantine: set[int]`, `.keyboard`;
    - methods:
      - `.connect(frame) -> Keyboard`;
      - `.drop(error=None)`;
      - `.reclaim(frame) -> Keyboard`.
  - Constants: `PERKEY`, `EFFECTS`, `ONBOARD`, `SW_ACTIVE`, `SW_RELEASE`, `ECHO`, `MAX_ABANDONED`.

**Ruling (spec conflict):** the spec's "Partial-claim rollback" says "reverse order (SetSWControl off, onboard mode back to 0x01)". Its "Release" lists the same two steps in the same order. That order was verified on hardware in Gate A, so rollback and release both use it: SetSWControl off, then onboard mode, then the profile re-select.

- [ ] **Step 1: Add the dependency**

In `g560ctl/pyproject.toml`, change `dependencies` to:

```toml
dependencies = [
  "pyusb>=1.2",
  "hidapi>=0.14",
  "python-xlib>=0.29",
]
```

Run: `g560ctl/.venv/bin/pip install -e g560ctl -q && g560ctl/.venv/bin/python -c "import hidraw; print('ok')"`
Expected: `ok`

- [ ] **Step 2: Write the failing tests**

`g560ctl/test/test_new_g815_keyboard.py`:

```python
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
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_keyboard.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'logitech_lighting.devices.g815.keyboard'`

- [ ] **Step 4: Write the implementation**

`g560ctl/src/logitech_lighting/devices/g815/keyboard.py`:

```python
"""G815 semantics on top of hidpp.Sender: discovery, claim/release, frames, control checks.

Byte sequences verified on hardware in Gate A (see the spec's "Gate A results"):
  claim    0x8071 fn5 [01 03 04], 0x8100 fn1 [02], 0x8081 fn0 [00 page 00] for pages 0-2
  release  0x8071 fn5 [01 00 00], 0x8100 fn1 [01], 0x8100 fn4 -> profile, 0x8100 fn3 [profile]
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from logitech_lighting.devices.g815.frame import FN_SET_INDIVIDUAL, FN_SET_RANGE, Write, encode
from logitech_lighting.devices.g815.hidpp import DeviceGone, Port, RequestFailed, Sender
from logitech_lighting.devices.g815.layout import BY_ZONE
from logitech_lighting.devices.g815.presets import Color

log = logging.getLogger(__name__)

VID, PID = 0x046D, 0xC33F
USAGE_PAGE, USAGE = 0xFF43, 0x0602

ROOT = 0x00
PERKEY, EFFECTS, ONBOARD = 0x8081, 0x8071, 0x8100
SW_ACTIVE = bytes([0x01, 0x03, 0x04])
SW_RELEASE = bytes([0x01, 0x00, 0x00])
MODE_ONBOARD, MODE_HOST = 0x01, 0x02
ECHO = {1: 1, 5: 1, 6: 4}       # Gate A: echoed parameter prefix per per-key write function
MAX_ABANDONED = 3
RECLAIM_WAIT = 1.0


class ClaimError(Exception):
    """Taking control failed; whatever the claim applied was rolled back."""


def parse_zone_page(page: int, params: bytes) -> set[int]:
    """0x8081 fn0 reply: params[2:16] is an LSB-first bitmap, zone = page*112 + byte*8 + bit."""
    return {page * 112 + i * 8 + b for i, byte in enumerate(params[2:16]) for b in range(8) if byte >> b & 1}


def usable_zones(discovered: set[int]) -> frozenset[int]:
    """Zones to paint: reported by the keyboard and present in layout.py (zone 0 has no LED)."""
    return frozenset(z for z in discovered if z in BY_ZONE)


def _zones_written(writes: list[Write]) -> int:
    n = 0
    for fn, params in writes:
        if fn == FN_SET_RANGE:
            n += sum(params[i + 1] - params[i] + 1 for i in range(0, len(params), 5))
        elif fn == FN_SET_INDIVIDUAL:
            n += len(params) // 4
        else:
            n += len(set(params[3:]))
    return n


class Keyboard:
    def __init__(self, sender: Sender) -> None:
        self.sender = sender
        self.idx: dict[int, int] = {}
        self.applied: set[str] = set()          # "sw" (SetSWControl), "host" (onboard mode 02)
        self.valid: frozenset[int] = frozenset()
        self.confirmed: dict[int, Color] | None = None
        self.abandoned = 0                      # consecutive abandoned frames
        self.committed = 0                      # frames acknowledged by frameEnd

    @property
    def needs_reclaim(self) -> bool:
        return self.abandoned >= MAX_ABANDONED

    def discover(self) -> dict[int, int]:
        self.idx = {}
        for fid in (PERKEY, EFFECTS, ONBOARD):
            index = self.sender.request(ROOT, 0, fid.to_bytes(2, "big"))[0]
            if index:
                self.idx[fid] = index
        return self.idx

    def claim(self, frame: dict[int, Color]) -> None:
        try:
            self.discover()
        except RequestFailed as exc:
            raise ClaimError(f"feature discovery failed: {exc}") from exc
        if PERKEY not in self.idx:
            raise ClaimError("keyboard has no per-key lighting feature 0x8081")
        self.applied = set()
        try:
            if EFFECTS in self.idx:
                self.sender.request(self.idx[EFFECTS], 5, SW_ACTIVE)
                self.applied.add("sw")
            if ONBOARD in self.idx:
                self.sender.request(self.idx[ONBOARD], 1, bytes([MODE_HOST]))
                self.applied.add("host")
            zones: set[int] = set()
            for page in range(3):
                zones |= parse_zone_page(page, self.sender.request(self.idx[PERKEY], 0, bytes([0, page, 0])))
            self.valid = usable_zones(zones)
            missing = set(BY_ZONE) - zones
            if missing:
                log.warning("layout zones not reported by the keyboard, never sent: %s",
                            " ".join(f"{z:#04x}" for z in sorted(missing)))
            self.confirmed = None
            if not self.send_frame(frame):
                raise ClaimError("base frame was not committed")
        except (RequestFailed, ClaimError) as exc:
            self._undo()
            raise ClaimError(str(exc)) from exc
        self.abandoned = 0

    def _undo(self) -> None:
        """Best effort, only what the claim applied. Order verified in Gate A."""
        try:
            if "sw" in self.applied:
                self.sender.request(self.idx[EFFECTS], 5, SW_RELEASE)
            if "host" in self.applied:
                self.sender.request(self.idx[ONBOARD], 1, bytes([MODE_ONBOARD]))
                profile = self.sender.request(self.idx[ONBOARD], 4)[:2]
                self.sender.request(self.idx[ONBOARD], 3, profile)   # makes the onboard effect reappear
        except RequestFailed as exc:
            log.warning("release step failed: %s", exc)
        self.applied = set()
        self.confirmed = None

    def release(self) -> None:
        try:
            self._undo()
        except DeviceGone as exc:
            log.warning("keyboard gone during release: %s", exc)

    def send_frame(self, frame: dict[int, Color], resync: tuple[int, ...] = ()) -> bool:
        """Send the changed zones, then frameEnd. True when the frame is committed (or empty)."""
        writes = encode(self.confirmed, frame, self.valid, resync)
        if not writes:
            return True
        perkey = self.idx[PERKEY]
        if not self.sender.send_writes(perkey, writes, ECHO):
            self.confirmed = None
            self.abandoned += 1
            return False
        self.abandoned = 0
        if self.sender.frame_end(perkey, _zones_written(writes)):
            self.confirmed = dict(frame)
            self.committed += 1
            return True
        self.confirmed = None
        return False

    def check_control(self) -> bool:
        """The 10 s check. False means control was lost and the caller must re-claim.

        With 0x8100 the onboard mode is read; without it SetSWControl is re-sent. Either
        way the cache is dropped, so the next frame is a full repaint that heals drift.
        """
        try:
            if "host" in self.applied:
                if self.sender.request(self.idx[ONBOARD], 2)[0] != MODE_HOST:
                    return False
            elif "sw" in self.applied:
                self.sender.request(self.idx[EFFECTS], 5, SW_ACTIVE)
        except RequestFailed:
            return False
        self.confirmed = None
        return True


def find_path() -> bytes | None:
    import hidraw  # never `hid`: that is the libusb backend and detaches the keyboard driver

    for entry in hidraw.enumerate(VID, PID):
        if entry["usage_page"] == USAGE_PAGE and entry["usage"] == USAGE:
            return entry["path"]
    return None


class HidrawPort:
    def __init__(self, path: bytes) -> None:
        import hidraw

        self._h = hidraw.device()
        self._h.open_path(path)

    def write(self, data: bytes) -> int:
        return self._h.write(data)

    def read(self, timeout_ms: int) -> bytes:
        return bytes(self._h.read(64, timeout_ms))

    def close(self) -> None:
        self._h.close()


class Connector:
    """Opens and claims the keyboard. Quarantined sw ids survive re-claims and handle
    reopens; only re-enumeration (the device seen absent, or its handle dying) resets them."""

    def __init__(
        self,
        find: Callable[[], bytes | None] = find_path,
        open_port: Callable[[bytes], Port] = HidrawPort,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._find = find
        self._open = open_port
        self._clock = clock
        self._sleep = sleep
        self.quarantine: set[int] = set()
        self._reenumerated = False
        self.keyboard: Keyboard | None = None

    def connect(self, frame: dict[int, Color]) -> Keyboard:
        path = self._find()
        if path is None:
            self._reenumerated = True
            raise DeviceGone("keyboard not found")
        if self._reenumerated:
            self.quarantine = set()
            self._reenumerated = False
        try:
            port = self._open(path)
        except OSError as exc:
            raise DeviceGone(f"cannot open {path!r}: {exc}") from exc
        keyboard = Keyboard(Sender(port, self.quarantine, self._clock, self._sleep))
        try:
            keyboard.claim(frame)
        except BaseException:
            port.close()
            raise
        self.keyboard = keyboard
        return keyboard

    def drop(self, error: DeviceGone | None = None) -> None:
        """Close the handle without talking to the keyboard."""
        if self.keyboard is not None:
            try:
                self.keyboard.sender.port.close()
            except OSError:
                pass
        self.keyboard = None
        if error is not None and error.io_error:
            self._reenumerated = True

    def reclaim(self, frame: dict[int, Color]) -> Keyboard:
        """Release, close, wait 1 s, reopen and claim again (quarantine kept)."""
        if self.keyboard is not None:
            self.keyboard.release()
        self.drop()
        self._sleep(RECLAIM_WAIT)
        return self.connect(frame)
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_keyboard.py -q`
Expected: `15 passed`

- [ ] **Step 6: Run the full suite and commit**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `94 passed`

```bash
git add g560ctl/pyproject.toml g560ctl/src/logitech_lighting/devices/g815/keyboard.py g560ctl/test/test_new_g815_keyboard.py
git commit -m "feat(g815): keyboard claim/release/frames and quarantine-preserving connector"
```

---

### Task 3: `state.py` — the state machine

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/state.py`
- Test: `g560ctl/test/test_new_g815_state.py`

**Interfaces:**
- **Produces:**
  - `State` (str enum): `OFF`, `DISCONNECTED`, `LOCKED`, `ACTIVE`, with values `"off"`, `"disconnected"`, `"locked"`, `"active"`.
  - `decide(off: bool, claimed: bool, locked: bool | None) -> State`.
  - `Effects(release, clear, rings)`.
  - `effects(prev: State, new: State) -> Effects`.

- [ ] **Step 1: Write the failing tests**

`g560ctl/test/test_new_g815_state.py`:

```python
import pytest

from logitech_lighting.devices.g815.state import State, decide, effects


@pytest.mark.parametrize("claimed", [True, False])
@pytest.mark.parametrize("locked", [True, False, None])
def test_off_is_sticky(claimed: bool, locked: bool | None) -> None:
    assert decide(off=True, claimed=claimed, locked=locked) is State.OFF


def test_unclaimed_is_disconnected() -> None:
    assert decide(off=False, claimed=False, locked=False) is State.DISCONNECTED


def test_lock_states() -> None:
    assert decide(off=False, claimed=True, locked=True) is State.LOCKED
    assert decide(off=False, claimed=True, locked=None) is State.LOCKED   # unknown -> locked
    assert decide(off=False, claimed=True, locked=False) is State.ACTIVE


def test_entering_locked_clears_rings() -> None:
    fx = effects(State.ACTIVE, State.LOCKED)
    assert fx.clear and not fx.rings and not fx.release


def test_entering_off_releases_only_when_claimed() -> None:
    assert effects(State.ACTIVE, State.OFF).release
    assert effects(State.LOCKED, State.OFF).release
    assert not effects(State.DISCONNECTED, State.OFF).release


def test_disconnected_to_claimed() -> None:
    assert effects(State.DISCONNECTED, State.ACTIVE).rings
    assert not effects(State.DISCONNECTED, State.LOCKED).rings
    assert effects(State.DISCONNECTED, State.LOCKED).clear


def test_losing_the_keyboard_clears_rings() -> None:
    fx = effects(State.ACTIVE, State.DISCONNECTED)
    assert fx.clear and not fx.release
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_state.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'logitech_lighting.devices.g815.state'`

- [ ] **Step 3: Write the implementation**

`g560ctl/src/logitech_lighting/devices/g815/state.py`:

```python
"""Daemon state machine (pure): the user's choice + observed conditions -> one state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    OFF = "off"                     # user chose `wave off`: keyboard released
    DISCONNECTED = "disconnected"   # wave wanted, keyboard absent or claim failed
    LOCKED = "locked"               # claimed, screen locked or lock state unknown: base only
    ACTIVE = "active"               # claimed, unlocked: rings live


def decide(off: bool, claimed: bool, locked: bool | None) -> State:
    """OFF is sticky; unknown lock state (None) counts as locked."""
    if off:
        return State.OFF
    if not claimed:
        return State.DISCONNECTED
    if locked is not False:
        return State.LOCKED
    return State.ACTIVE


@dataclass(frozen=True)
class Effects:
    release: bool   # hand the keyboard back to onboard lighting
    clear: bool     # drop every ring now, so the next frame is all base
    rings: bool     # presses start rings in the new state


def effects(prev: State, new: State) -> Effects:
    claimed = (State.LOCKED, State.ACTIVE)
    return Effects(
        release=new is State.OFF and prev in claimed,
        clear=new is not State.ACTIVE and prev is not new,
        rings=new is State.ACTIVE,
    )
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_state.py -q`
Expected: `12 passed`

- [ ] **Step 5: Run the full suite and commit**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `106 passed`

```bash
git add g560ctl/src/logitech_lighting/devices/g815/state.py g560ctl/test/test_new_g815_state.py
git commit -m "feat(g815): wave daemon state machine"
```

---

### Task 4: `keys.py` — XI2 raw key presses

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/keys.py`
- Test: `g560ctl/test/test_new_g815_keys.py`

**Interfaces:**
- **Consumes:** `BY_EVDEV` (Part 1 `layout.py`); `FakeClock` (Task 1).
- **Produces:**
  - `RawKey(deviceid, time, detail, sourceid)` and `decode_raw(data) -> RawKey`.
  - `KeyFilter(query_ids, clock=time.monotonic)`:
    - attribute `.ids`;
    - methods:
      - `.hierarchy_changed()`;
      - `.tick()`;
      - `.key_name(raw) -> str | None`.
  - `XKeySource(display_name=None)`:
    - attribute `.filter`;
    - methods:
      - `.fileno()`;
      - `.poll() -> list[str]` (raises python-xlib's `ConnectionClosedError` on X loss);
      - `.close()`.
  - `XInputTooOld`.
  - Constant `HIERARCHY_SETTLE = 0.25`.

`ev.data` for `XI_RawKeyPress` holds the raw bytes after the 10-byte generic-event header. python-xlib registers no decoder for raw events (verified: `Xlib/ext/xinput.py` registers only device, DeviceChanged, HierarchyChanged and Property events), so `decode_raw` unpacks them itself. Unlike the Gate B probe, this module does not call `ge_add_event_data`.

- [ ] **Step 1: Write the failing tests**

`g560ctl/test/test_new_g815_keys.py`:

```python
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
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_keys.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'logitech_lighting.devices.g815.keys'`

- [ ] **Step 3: Write the implementation**

`g560ctl/src/logitech_lighting/devices/g815/keys.py`:

```python
"""X11 XInput 2.2 raw key presses from the G815 only (spec "Keypress input").

python-xlib negotiates XI 2.0 and has no RawKeyPress decoder, so this module sends
XIQueryVersion 2.2 itself (before any other XI request) and decodes the raw
generic-event bytes. Key presses are kept only as key names, never logged.
"""
from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass
from typing import Callable

from logitech_lighting.devices.g815.layout import BY_EVDEV

log = logging.getLogger(__name__)

G815_NAME = "Logitech G815 RGB MECHANICAL GAMING KEYBOARD"
XI_HIERARCHY_CHANGED = 11
XI_RAW_KEY_PRESS = 13
SLAVE_KEYBOARD = 4
HIERARCHY_SETTLE = 0.25     # Gate B: one replug fires ~16 hierarchy events; re-query once after

# XI2 raw event body after the 10-byte generic-event header, in the client's byte order.
_RAW = struct.Struct("=HIIH")


class XInputTooOld(Exception):
    pass


@dataclass(frozen=True)
class RawKey:
    deviceid: int
    time: int
    detail: int      # X keycode
    sourceid: int    # the slave device that produced the key


def decode_raw(data: bytes) -> RawKey:
    return RawKey(*_RAW.unpack_from(data))


class KeyFilter:
    """Keeps the G815's slave ids current and maps accepted raw events to key names."""

    def __init__(self, query_ids: Callable[[], set[int]], clock: Callable[[], float] = time.monotonic) -> None:
        self._query = query_ids
        self._clock = clock
        self.ids = query_ids()
        self._last_change: float | None = None
        self._unmapped: set[int] = set()

    def hierarchy_changed(self) -> None:
        self._last_change = self._clock()

    def tick(self) -> None:
        if self._last_change is not None and self._clock() - self._last_change >= HIERARCHY_SETTLE:
            self._last_change = None
            self.ids = self._query()
            log.info("G815 input devices: %s", sorted(self.ids))

    def key_name(self, raw: RawKey) -> str | None:
        if raw.sourceid not in self.ids:
            return None
        key = BY_EVDEV.get(raw.detail - 8)
        if key is None:
            if raw.detail not in self._unmapped:
                self._unmapped.add(raw.detail)
                log.debug("unmapped X keycode %d ignored", raw.detail)
            return None
        return key.name


class XKeySource:
    def __init__(self, display_name: str | None = None) -> None:
        from Xlib import display
        from Xlib.ext import xinput

        self._xinput = xinput
        self._d = display.Display(display_name)
        self._opcode = self._d.display.get_extension_major("XInputExtension")
        v = xinput.XIQueryVersion(display=self._d.display, opcode=self._opcode,
                                  major_version=2, minor_version=2)
        if (v.major_version, v.minor_version) < (2, 1):
            raise XInputTooOld(f"X server offers XInput {v.major_version}.{v.minor_version}, need >= 2.1")
        self._d.screen().root.xinput_select_events([
            (xinput.AllMasterDevices, 1 << XI_RAW_KEY_PRESS),
            (xinput.AllDevices, 1 << XI_HIERARCHY_CHANGED),
        ])
        self.filter = KeyFilter(self._g815_ids)

    def _g815_ids(self) -> set[int]:
        info = self._d.xinput_query_device(self._xinput.AllDevices)
        return {dev.deviceid for dev in info.devices
                if dev.name.startswith(G815_NAME) and dev.use == SLAVE_KEYBOARD}

    def fileno(self) -> int:
        return self._d.fileno()

    def poll(self) -> list[str]:
        """Key names pressed on the G815 since the last call. Raises on X connection loss."""
        names: list[str] = []
        while self._d.pending_events():
            ev = self._d.next_event()
            if getattr(ev, "extension", None) != self._opcode:
                continue
            if ev.evtype == XI_HIERARCHY_CHANGED:
                self.filter.hierarchy_changed()
            elif ev.evtype == XI_RAW_KEY_PRESS:
                name = self.filter.key_name(decode_raw(ev.data))
                if name is not None:
                    names.append(name)
        self.filter.tick()
        return names

    def close(self) -> None:
        self._d.close()
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_keys.py -q`
Expected: `4 passed`

- [ ] **Step 5: Live check against the X server (no typing needed)**

Run:

```bash
g560ctl/.venv/bin/python - <<'EOF'
import subprocess, time
from logitech_lighting.devices.g815 import keys
src = keys.XKeySource()
print("g815 ids:", sorted(src.filter.ids))
rejected = []
orig = src.filter.key_name
src.filter.key_name = lambda raw: (rejected.append((raw.sourceid, raw.detail)) if raw.sourceid not in src.filter.ids else None) or orig(raw)
subprocess.run(["xdotool", "key", "a"])
time.sleep(0.3)
print("accepted:", src.poll(), "rejected:", rejected)
src.close()
EOF
```

Expected:
- `g815 ids: [15, 16]`, or the current ids;
- `accepted: []`;
- `rejected:` includes `(5, 38)`, meaning the XTEST keyboard sent keycode 38 (`a`).

If you or the user type at the same moment, extra entries may appear. Re-run.

- [ ] **Step 6: Run the full suite and commit**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `110 passed`

```bash
git add g560ctl/src/logitech_lighting/devices/g815/keys.py g560ctl/test/test_new_g815_keys.py
git commit -m "feat(g815): XI2.2 raw key source filtered to the G815"
```

---

### Task 5: `daemon.py` core — state file, lock query, the `Daemon` loop logic

**Files:**
- Create: `g560ctl/src/logitech_lighting/devices/g815/daemon.py` (core; Task 6 appends the service plumbing)
- Modify: `g560ctl/test/g815_fakes.py` (append the daemon doubles)
- Test: `g560ctl/test/test_new_g815_daemon.py`

**Interfaces:**
- **Consumes:**
  - `Connector`, `Keyboard`, `ClaimError` (Task 2); `DeviceGone` (Task 1);
  - `State`, `decide`, `effects` (Task 3);
  - `Ripple` (Part 1); `ResyncRotor` (Part 1); `PRESETS`, `BASE` (Part 1).
- **Produces:**
  - `StateFile(path)` with `.load() -> (preset, off)` and `.save(preset, off)`.
  - `query_lock(run=subprocess.run) -> bool | None`.
  - `LockWatcher(query, interval)`, a thread with `.locked` and `.stop()`.
  - `Daemon(connector, keys, lock_state, state_file)`:
    - methods:
      - `.handle(req: dict, now) -> dict`;
      - `.tick(now)`;
      - `.status() -> dict` (keys `preset`, `state`, `connected`, `lock`, `fps`);
      - `.fps() -> float`;
      - `.shutdown()`.
    - attributes: `.state`, `.preset`, `.off`, `.kb`.
  - Helpers: `runtime_dir(env)`, `socket_path(env)`, `default_state_path()`, `base_frame()`.
  - Constants: `CONTROL_CHECK`, `RECONNECT_POLL`, `CLAIM_BACKOFF`, `FRAME_INTERVAL`, `SOCKET_NAME`, `LOCK_NAME`, `ENV_HINT`.
  - Test doubles in `g815_fakes`: `FakeKb`, `FakeConnector`, `FakeKeys`.

- [ ] **Step 1: Append the daemon doubles to `g560ctl/test/g815_fakes.py`**

Change its layout import line to:

```python
from logitech_lighting.devices.g815.layout import KEYS, PHASE1_VALID_ZONES
```

Then append:

```python
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

    def send_frame(self, frame, resync=()):
        if self.fail:
            raise self.fail
        if not self.frames or self.frames[-1] != frame:
            self.committed += 1
        self.frames.append(frame)
        return True

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
```

- [ ] **Step 2: Write the failing tests**

`g560ctl/test/test_new_g815_daemon.py`:

```python
import json
import subprocess

import pytest

from g815_fakes import FakeConnector, FakeKeys
from logitech_lighting.devices.g815.daemon import (
    CLAIM_BACKOFF, CONTROL_CHECK, RECONNECT_POLL, Daemon, StateFile, query_lock,
)
from logitech_lighting.devices.g815.hidpp import DeviceGone
from logitech_lighting.devices.g815.keyboard import ClaimError
from logitech_lighting.devices.g815.layout import BY_NAME
from logitech_lighting.devices.g815.presets import BASE, PRESETS
from logitech_lighting.devices.g815.state import State


def _daemon(tmp_path, locked=False, state=None):
    path = tmp_path / "wave.json"
    if state is not None:
        path.write_text(json.dumps(state))
    lock = {"value": locked}
    conn, keys = FakeConnector(), FakeKeys()
    d = Daemon(conn, keys, lambda: lock["value"], StateFile(path))
    return d, conn, keys, lock


def test_state_file_round_trip_and_default(tmp_path) -> None:
    sf = StateFile(tmp_path / "sub" / "wave.json")
    assert sf.load() == ("red", False)
    sf.save("blue", True)
    assert sf.load() == ("blue", True)


@pytest.mark.parametrize("content", ["{not json", '{"preset": "green", "off": false}', '{"preset": "red"}', "[]"])
def test_corrupt_state_file_falls_back_and_is_rewritten(tmp_path, content) -> None:
    path = tmp_path / "wave.json"
    path.write_text(content)
    assert StateFile(path).load() == ("red", False)
    assert json.loads(path.read_text()) == {"preset": "red", "off": False}


@pytest.mark.parametrize("stdout,code,expected", [
    ("(true,)\n", 0, True), ("(false,)\n", 0, False), ("garbage", 0, None), ("", 1, None),
])
def test_query_lock_parses_gdbus(stdout, code, expected) -> None:
    run = lambda *a, **k: subprocess.CompletedProcess(a, code, stdout=stdout, stderr="")
    assert query_lock(run) is expected


@pytest.mark.parametrize("exc", [FileNotFoundError("gdbus"), subprocess.TimeoutExpired("gdbus", 0.5)])
def test_query_lock_failure_is_unknown(exc) -> None:
    def run(*a, **k):
        raise exc
    assert query_lock(run) is None


def test_connects_then_active_when_unlocked(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    assert d.state is State.ACTIVE and conn.connects == 1


def test_unknown_lock_state_means_locked(tmp_path) -> None:
    d, _, _, _ = _daemon(tmp_path, locked=None)
    d.tick(10.0)
    assert d.state is State.LOCKED and d.status()["lock"] == "unknown"


def test_presses_ripple_only_when_active(tmp_path) -> None:
    d, conn, keys, lock = _daemon(tmp_path, locked=True)
    d.tick(10.0)
    keys.pending = ["g"]
    d.tick(10.02)
    assert set(conn.kb.frames[-1].values()) == {BASE}
    lock["value"] = False
    keys.pending = ["g"]
    d.tick(10.04)
    d.tick(10.06)
    assert conn.kb.frames[-1][BY_NAME["g"].zone] == PRESETS["red"].stops[0]


def test_locking_clears_rings_and_commits_base_at_once(tmp_path) -> None:
    d, conn, keys, lock = _daemon(tmp_path)
    d.tick(10.0)
    keys.pending = ["g"]
    d.tick(10.02)
    lock["value"] = True
    d.tick(10.04)
    assert d.state is State.LOCKED and set(conn.kb.frames[-1].values()) == {BASE}


def test_off_releases_and_is_sticky(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    reply = d.handle({"cmd": "off"}, 10.1)
    assert reply["ok"] and reply["state"] == "off" and conn.kb.released == 1
    for i in range(50):
        d.tick(11.0 + i)
    assert conn.connects == 1
    assert json.loads((tmp_path / "wave.json").read_text()) == {"preset": "red", "off": True}


def test_off_state_file_means_no_claim_at_start(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path, state={"preset": "blue", "off": True})
    d.tick(10.0)
    assert d.state is State.OFF and conn.connects == 0


def test_preset_command_leaves_off_and_switches_colors(tmp_path) -> None:
    d, conn, keys, _ = _daemon(tmp_path, state={"preset": "red", "off": True})
    reply = d.handle({"cmd": "preset", "name": "blue"}, 10.0)
    assert reply["ok"] and reply["preset"] == "blue"
    d.tick(10.0)
    keys.pending = ["g"]
    d.tick(10.02)
    d.tick(10.04)
    assert d.state is State.ACTIVE
    assert conn.kb.frames[-1][BY_NAME["g"].zone] == PRESETS["blue"].stops[0]


def test_bad_commands_list_valid_choices(tmp_path) -> None:
    d, _, _, _ = _daemon(tmp_path)
    bad = d.handle({"cmd": "preset", "name": "green"}, 1.0)
    assert not bad["ok"] and "blue, red" in bad["error"]
    assert not d.handle({"cmd": "dance"}, 1.0)["ok"]


def test_absent_keyboard_polls_every_2s(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    conn.error = DeviceGone("keyboard not found")
    d.tick(10.0)
    d.tick(10.0 + RECONNECT_POLL / 2)
    assert conn.connects == 1
    d.tick(10.0 + RECONNECT_POLL)
    assert conn.connects == 2 and d.state is State.DISCONNECTED


def test_claim_failures_back_off(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    conn.error = ClaimError("nope")
    d.tick(10.0)
    d.tick(10.0 + CLAIM_BACKOFF[0])
    d.tick(10.0 + CLAIM_BACKOFF[0] + CLAIM_BACKOFF[1] - 0.1)
    assert conn.connects == 2


def test_keyboard_loss_goes_disconnected_then_reconnects(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    conn.kb.fail = DeviceGone("write failed", io_error=True)
    d.tick(10.02)
    assert d.state is State.DISCONNECTED and conn.drops[-1].io_error
    conn.kb.fail = None
    d.tick(10.02 + RECONNECT_POLL)
    assert d.state is State.ACTIVE and conn.connects == 2


def test_takeover_and_abandoned_frames_reclaim(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    conn.kb.control_ok = False
    d.tick(10.0 + CONTROL_CHECK)
    assert conn.reclaims == 1
    conn.kb.control_ok = True
    conn.kb.needs_reclaim = True
    d.tick(10.0 + CONTROL_CHECK + 0.02)
    assert conn.reclaims == 2


def test_fps_reports_last_burst(tmp_path) -> None:
    d, _, _, _ = _daemon(tmp_path)
    for i in range(31):
        d._commits.append(100.0 + i / 30)
    for i in range(5):
        d._commits.append(200.0 + i)                          # sparse, not a burst
    assert d.fps() == 0.0
    d._commits.clear()
    for i in range(31):
        d._commits.append(300.0 + i / 30)
    assert d.fps() == pytest.approx(30.0)


def test_leaving_off_connects_immediately(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    conn.error = ClaimError("busy keyboard")
    for i in range(5):                                        # next retry 30 s away
        d.tick(10.0 + sum(CLAIM_BACKOFF[:i]))
    d.handle({"cmd": "off"}, 40.5)
    conn.error = None
    d.handle({"cmd": "preset", "name": "red"}, 41.0)
    d.tick(41.0)
    assert d.state is State.ACTIVE


def test_unwritable_state_file_keeps_running(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.state_file.path = tmp_path / "missing-dir-file" / "x" / "wave.json"
    (tmp_path / "missing-dir-file").write_text("a file, so mkdir under it fails")
    d.tick(10.0)
    assert d.handle({"cmd": "off"}, 10.1)["ok"] and conn.kb.released == 1


def test_press_on_lock_tick_does_not_ring(tmp_path) -> None:
    d, conn, keys, lock = _daemon(tmp_path)
    d.tick(10.0)
    lock["value"] = True
    keys.pending = ["g"]
    d.tick(10.02)
    assert set(conn.kb.frames[-1].values()) == {BASE}


def test_failed_reclaim_goes_disconnected_and_retries(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    conn.kb.control_ok = False
    conn.error = ClaimError("still taken")
    d.tick(10.0 + CONTROL_CHECK)
    assert d.state is State.DISCONNECTED
    conn.error = None
    conn.kb.control_ok = True
    d.tick(10.0 + CONTROL_CHECK + CLAIM_BACKOFF[0])
    assert d.state is State.ACTIVE
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_daemon.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'logitech_lighting.devices.g815.daemon'`

- [ ] **Step 4: Write the implementation**

`g560ctl/src/logitech_lighting/devices/g815/daemon.py`:

```python
"""The wave daemon: frame loop, control socket, state file, lock-screen watch, reconnect."""
from __future__ import annotations

import collections
import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

from logitech_lighting.devices.g815.frame import ResyncRotor
from logitech_lighting.devices.g815.hidpp import DeviceGone
from logitech_lighting.devices.g815.keyboard import ClaimError, Connector, Keyboard
from logitech_lighting.devices.g815.layout import KEYS
from logitech_lighting.devices.g815.presets import BASE, PRESETS, Color
from logitech_lighting.devices.g815.ripple import Ripple
from logitech_lighting.devices.g815.state import State, decide, effects

log = logging.getLogger("g815-wave")

DEFAULT_PRESET = "red"
FRAME_INTERVAL = 1 / 60
CONTROL_CHECK = 10.0
RECONNECT_POLL = 2.0
CLAIM_BACKOFF = (2.0, 4.0, 8.0, 16.0, 30.0)
LOCK_POLL = 1.0
GDBUS = "/usr/bin/gdbus"
SOCKET_NAME = "g815-wave.sock"
LOCK_NAME = "g815-wave.lock"
ENV_HINT = "systemctl --user import-environment DISPLAY XAUTHORITY"


def runtime_dir(env: dict[str, str] | os._Environ = os.environ) -> Path:
    return Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def socket_path(env: dict[str, str] | os._Environ = os.environ) -> Path:
    return runtime_dir(env) / SOCKET_NAME


def default_state_path() -> Path:
    return Path.home() / ".config" / "logitech-lighting" / "wave.json"


def base_frame() -> dict[int, Color]:
    return {k.zone: BASE for k in KEYS}


class StateFile:
    """The user's choice only: {"preset": "red"|"blue", "off": bool}."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[str, bool]:
        try:
            data = json.loads(self.path.read_text())
            preset, off = data["preset"], data["off"]
            if preset not in PRESETS or not isinstance(off, bool):
                raise ValueError(f"bad values {data!r}")
            return preset, off
        except FileNotFoundError:
            return DEFAULT_PRESET, False
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("corrupt state file %s (%s); using defaults", self.path, exc)
            try:
                self.save(DEFAULT_PRESET, False)
            except OSError as save_exc:
                log.warning("cannot rewrite %s: %s", self.path, save_exc)
            return DEFAULT_PRESET, False

    def save(self, preset: str, off: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"preset": preset, "off": off}) + "\n")
        tmp.replace(self.path)


def query_lock(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool | None:
    """GNOME ScreenSaver GetActive: True/False, or None when unknown (treated as locked)."""
    try:
        out = run([GDBUS, "call", "--session", "--dest", "org.gnome.ScreenSaver",
                   "--object-path", "/org/gnome/ScreenSaver",
                   "--method", "org.gnome.ScreenSaver.GetActive"],
                  capture_output=True, text=True, timeout=0.5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return {"(true,)": True, "(false,)": False}.get(out.stdout.strip())


class LockWatcher(threading.Thread):
    """Polls the lock state off the frame loop, so a slow gdbus never stalls frames."""

    def __init__(self, query: Callable[[], bool | None] = query_lock, interval: float = LOCK_POLL) -> None:
        super().__init__(name="lock-watch", daemon=True)
        self._query = query
        self._interval = interval
        self._stop = threading.Event()
        self.locked: bool | None = None

    def run(self) -> None:
        while not self._stop.is_set():
            self.locked = self._query()
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()


class Daemon:
    def __init__(
        self,
        connector: Connector,
        keys,                                   # .poll() -> list[str] of key names
        lock_state: Callable[[], bool | None],
        state_file: StateFile,
    ) -> None:
        self.connector = connector
        self.keys = keys
        self.lock_state = lock_state
        self.state_file = state_file
        self.preset, self.off = state_file.load()
        self.ripple = Ripple(preset=PRESETS[self.preset])
        self.ripple.pause()
        self.kb: Keyboard | None = None
        self.rotor: ResyncRotor | None = None
        self.state = State.OFF if self.off else State.DISCONNECTED
        self.locked: bool | None = None
        self._lock_warned = False
        self._next_connect = 0.0
        self._backoff = 0
        self._last_check = 0.0
        self._commits: collections.deque[float] = collections.deque(maxlen=64)

    # -- control socket commands ------------------------------------------

    def handle(self, req: dict, now: float) -> dict:
        cmd = req.get("cmd")
        if cmd == "preset":
            name = req.get("name")
            if name not in PRESETS:
                return {"ok": False, "error": f"unknown preset {name!r}; choose one of: {', '.join(sorted(PRESETS))}"}
            if self.off:
                self._next_connect, self._backoff = now, 0     # leaving OFF: connect at once
            self.preset, self.off = name, False
            self.ripple.set_preset(PRESETS[name])
            self._save()
            self._apply(now)
            return {"ok": True, **self.status()}
        if cmd == "off":
            self.off = True
            self._save()
            self._apply(now)
            return {"ok": True, **self.status()}
        if cmd == "status":
            return {"ok": True, **self.status()}
        return {"ok": False, "error": "unknown command; valid: preset, off, status"}

    def _save(self) -> None:
        try:
            self.state_file.save(self.preset, self.off)
        except OSError as exc:
            log.warning("cannot save %s: %s", self.state_file.path, exc)

    def status(self) -> dict:
        return {
            "preset": self.preset,
            "state": self.state.value,
            "connected": self.kb is not None,
            "lock": "unknown" if self.locked is None else ("locked" if self.locked else "unlocked"),
            "fps": round(self.fps(), 1),
        }

    def fps(self) -> float:
        """Committed frames per second over the most recent burst of frames."""
        times = list(self._commits)
        run = times[-1:]
        for a, b in zip(reversed(times[:-1]), reversed(times[1:])):
            if b - a > 0.1:
                break
            run.insert(0, a)
        if len(run) < 2:
            return 0.0
        return (len(run) - 1) / (run[-1] - run[0])

    # -- one loop iteration --------------------------------------------------

    def tick(self, now: float) -> None:
        presses = self.keys.poll()                  # X connection loss propagates to run_daemon
        self.locked = self.lock_state()
        if self.locked is None and not self._lock_warned:
            log.warning("lock state unknown (GNOME ScreenSaver not answering); rings paused")
        self._lock_warned = self.locked is None
        self._apply(now)
        if self.state is State.ACTIVE:
            for name in presses:
                self.ripple.press(name, now)
        if self.state in (State.LOCKED, State.ACTIVE):
            self._frame(now)
        elif self.state is State.DISCONNECTED and now >= self._next_connect:
            self._connect(now)
            self._apply(now)
            if self.state in (State.LOCKED, State.ACTIVE):
                self._frame(now)

    def _apply(self, now: float) -> None:
        new = decide(self.off, self.kb is not None, self.locked)
        if new is self.state:
            return
        fx = effects(self.state, new)
        if fx.clear:
            self.ripple.clear()
        if fx.release and self.kb is not None:
            self.kb.release()
            self.connector.drop()
            self.kb = None
        if fx.rings:
            self.ripple.resume()
        else:
            self.ripple.pause()
        log.info("state %s -> %s", self.state.value, new.value)
        self.state = new

    def _connect(self, now: float) -> None:
        try:
            self.kb = self.connector.connect(base_frame())
        except DeviceGone as exc:
            log.debug("keyboard not available: %s", exc)
            self._next_connect = now + RECONNECT_POLL
            return
        except ClaimError as exc:
            delay = CLAIM_BACKOFF[min(self._backoff, len(CLAIM_BACKOFF) - 1)]
            self._backoff += 1
            log.warning("claim failed (%s); retrying in %.0f s", exc, delay)
            self._next_connect = now + delay
            return
        self._backoff = 0
        self._last_check = now
        self.rotor = ResyncRotor(self.kb.valid)
        log.info("keyboard claimed (%d zones)", len(self.kb.valid))

    def _lost(self, exc: DeviceGone, now: float) -> None:
        log.warning("keyboard lost: %s", exc)
        self.connector.drop(exc)
        self.kb = None
        self._next_connect = now + RECONNECT_POLL
        self._apply(now)

    def _reclaim(self, now: float) -> None:
        log.warning("re-claiming the keyboard")
        try:
            self.kb = self.connector.reclaim(base_frame())
            self.rotor = ResyncRotor(self.kb.valid)
            self._last_check = now
        except DeviceGone as exc:
            self._lost(exc, now)
        except ClaimError as exc:
            log.warning("re-claim failed: %s", exc)
            self.kb = None
            self._next_connect = now + CLAIM_BACKOFF[0]
            self._apply(now)

    def _frame(self, now: float) -> None:
        assert self.kb is not None and self.rotor is not None
        try:
            if now - self._last_check >= CONTROL_CHECK:
                self._last_check = now
                if not self.kb.check_control():
                    self._reclaim(now)
                    return
            before = self.kb.committed
            self.kb.send_frame(self.ripple.render(now), self.rotor.next())
            if self.kb.committed > before:
                self._commits.append(now)
            if self.kb.needs_reclaim:
                self._reclaim(now)
        except DeviceGone as exc:
            self._lost(exc, now)

    def shutdown(self) -> None:
        if self.kb is not None:
            self.kb.release()
            self.connector.drop()
            self.kb = None
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_daemon.py -q`
Expected: `28 passed`

- [ ] **Step 6: Run the full suite and commit**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `138 passed`

```bash
git add g560ctl/src/logitech_lighting/devices/g815/daemon.py g560ctl/test/g815_fakes.py g560ctl/test/test_new_g815_daemon.py
git commit -m "feat(g815): wave daemon core - state file, lock watch, state transitions, reconnect"
```

---

### Task 6: Service plumbing, `wave` CLI

**Files:**
- Modify: `g560ctl/src/logitech_lighting/devices/g815/daemon.py` (imports + append the service plumbing)
- Create: `g560ctl/src/logitech_lighting/devices/g815/wave_cli.py`
- Modify: `g560ctl/src/logitech_lighting/cli.py` (the `wave` subparser + early dispatch)
- Test: `g560ctl/test/test_new_g815_service.py`

**Interfaces:**
- **Consumes:** everything in `daemon.py` from Task 5; `XKeySource`, `XInputTooOld` (Task 4); `Connector` (Task 2).
- **Produces:**
  - In `daemon.py`:
    - `acquire_lock(path) -> int | None`;
    - `bind_socket(path) -> socket`;
    - `serve(daemon, listener, stop, clock=time.monotonic, wake_fd=None)`;
    - `run_daemon(env=os.environ, make_keys=None, make_connector=Connector, lock_query=query_lock, state_path=None, stop=None) -> int`.
  - In `wave_cli.py`:
    - `DaemonNotRunning`;
    - `send_command(req, path=None, timeout=3.0) -> dict`;
    - `format_status(reply) -> str`;
    - `run_wave(action, path=None) -> int`;
    - `NOT_RUNNING`.

- [ ] **Step 1: Write the failing tests**

`g560ctl/test/test_new_g815_service.py`:

```python
import json
import os
import socket
import threading

import pytest

from g815_fakes import FakeConnector, FakeKeys
from logitech_lighting.devices.g815 import daemon as dmod
from logitech_lighting.devices.g815.daemon import (
    Daemon, StateFile, acquire_lock, bind_socket, run_daemon, serve,
)
from logitech_lighting.devices.g815.wave_cli import NOT_RUNNING, send_command


def _daemon(tmp_path):
    return Daemon(FakeConnector(), FakeKeys(), lambda: False, StateFile(tmp_path / "wave.json"))


def _serving(tmp_path):
    """Start serve() on a thread; returns (stop, thread, listener)."""
    listener = bind_socket(tmp_path / "w.sock")
    stop = threading.Event()
    t = threading.Thread(target=serve, args=(_daemon(tmp_path), listener, stop))
    t.start()
    return stop, t, listener


def test_lock_is_exclusive(tmp_path) -> None:
    first = acquire_lock(tmp_path / "w.lock")
    assert first is not None
    assert acquire_lock(tmp_path / "w.lock") is None
    os.close(first)
    again = acquire_lock(tmp_path / "w.lock")
    assert again is not None
    os.close(again)


def test_bind_socket_replaces_stale_file_with_0600(tmp_path) -> None:
    path = tmp_path / "w.sock"
    path.write_text("stale")
    sock = bind_socket(path)
    try:
        assert oct(path.stat().st_mode & 0o777) == "0o600"
    finally:
        sock.close()


def test_socket_round_trip(tmp_path) -> None:
    stop, t, listener = _serving(tmp_path)
    try:
        assert send_command({"cmd": "status"}, tmp_path / "w.sock")["ok"]
        assert send_command({"cmd": "preset", "name": "blue"}, tmp_path / "w.sock")["preset"] == "blue"
    finally:
        stop.set()
        t.join(2)
        listener.close()


def _env(tmp_path, **extra):
    return {"XDG_RUNTIME_DIR": str(tmp_path), "DISPLAY": ":1", "XAUTHORITY": "/x", **extra}


def test_missing_display_exits_0_with_hint(tmp_path, caplog) -> None:
    env = _env(tmp_path)
    del env["XAUTHORITY"]
    assert run_daemon(env=env) == 0
    assert "import-environment DISPLAY XAUTHORITY" in caplog.text


def test_second_daemon_exits_already_running_and_keeps_socket(tmp_path, capsys) -> None:
    held = acquire_lock(tmp_path / dmod.LOCK_NAME)
    (tmp_path / dmod.SOCKET_NAME).write_text("live daemon's socket")
    try:
        assert run_daemon(env=_env(tmp_path), make_keys=FakeKeys) == 1
        assert "already running" in capsys.readouterr().out
        assert (tmp_path / dmod.SOCKET_NAME).read_text() == "live daemon's socket"
    finally:
        os.close(held)


def test_x_connection_loss_releases_and_exits_0(tmp_path) -> None:
    from Xlib.error import ConnectionClosedError

    conn = FakeConnector()
    keys = FakeKeys()
    polls = {"n": 0}

    def poll():
        polls["n"] += 1
        if polls["n"] >= 3:
            raise ConnectionClosedError("display")
        return []

    keys.poll = poll
    code = run_daemon(env=_env(tmp_path), make_keys=lambda: keys, make_connector=lambda: conn,
                      lock_query=lambda: False, state_path=tmp_path / "wave.json")
    assert code == 0 and conn.kb.released == 1
    assert not (tmp_path / dmod.SOCKET_NAME).exists()


def test_cli_without_daemon_says_not_running(tmp_path, monkeypatch, capsys) -> None:
    from logitech_lighting import cli

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "UnifiedController", lambda *a, **k: pytest.fail("G560 touched"))
    monkeypatch.setattr(cli, "get_default_device", lambda: pytest.fail("G560 probed"))
    assert cli.main(["wave", "status"]) == 1
    assert NOT_RUNNING in capsys.readouterr().err


def test_garbage_request_gets_error_reply(tmp_path) -> None:
    stop, t, listener = _serving(tmp_path)
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(str(tmp_path / "w.sock"))
            s.sendall(b"not json\n")
            assert json.loads(s.makefile().readline()) == {"ok": False, "error": "bad request"}
        assert send_command({"cmd": "status"}, tmp_path / "w.sock")["ok"]
    finally:
        stop.set()
        t.join(2)
        listener.close()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_service.py -q`
Expected: FAIL with `ImportError: cannot import name 'acquire_lock' from 'logitech_lighting.devices.g815.daemon'`

- [ ] **Step 3: Extend `daemon.py`**

Replace its import block (from `import collections` through `from pathlib import Path`) with:

```python
import collections
import fcntl
import json
import logging
import os
import selectors
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
```

Then append to the end of the file:

```python
# -- service plumbing ---------------------------------------------------------

def acquire_lock(path: Path) -> int | None:
    """Exclusive flock held for the daemon's lifetime; None if another daemon holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def bind_socket(path: Path) -> socket.socket:
    """Only the lock holder calls this, so removing a leftover socket file is safe."""
    path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        sock.bind(str(path))
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    sock.listen(4)
    sock.setblocking(False)
    return sock


def _serve_client(listener: socket.socket, daemon: Daemon, now: float) -> None:
    try:
        conn, _ = listener.accept()
    except BlockingIOError:
        return
    with conn:
        conn.settimeout(1.0)
        try:
            data = b""
            while not data.endswith(b"\n") and len(data) < 4096:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            try:
                req = json.loads(data)
                reply = daemon.handle(req, now) if isinstance(req, dict) else {"ok": False, "error": "bad request"}
            except ValueError:
                reply = {"ok": False, "error": "bad request"}
            conn.sendall(json.dumps(reply).encode() + b"\n")
        except OSError as exc:
            log.debug("control client error: %s", exc)


def serve(daemon: Daemon, listener: socket.socket, stop: threading.Event,
          clock: Callable[[], float] = time.monotonic, wake_fd: int | None = None) -> None:
    sel = selectors.DefaultSelector()
    sel.register(listener, selectors.EVENT_READ)
    if wake_fd is not None:
        sel.register(wake_fd, selectors.EVENT_READ)
    next_tick = clock()
    try:
        while not stop.is_set():
            for key, _ in sel.select(max(0.0, next_tick - clock())):
                if key.fileobj is listener:
                    _serve_client(listener, daemon, clock())
                else:
                    next_tick = clock()          # X input arrived: handle presses now
            now = clock()
            if now >= next_tick:
                daemon.tick(now)
                next_tick = now + FRAME_INTERVAL
    finally:
        sel.close()


def run_daemon(
    env: dict[str, str] | os._Environ = os.environ,
    make_keys: Callable[[], object] | None = None,
    make_connector: Callable[[], Connector] = Connector,
    lock_query: Callable[[], bool | None] = query_lock,
    state_path: Path | None = None,
    stop: threading.Event | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not env.get("DISPLAY") or not env.get("XAUTHORITY"):
        log.error("DISPLAY/XAUTHORITY missing from the service environment; run: %s", ENV_HINT)
        return 0
    rt = runtime_dir(env)
    lock_fd = acquire_lock(rt / LOCK_NAME)
    if lock_fd is None:
        print("g815 wave daemon already running")
        return 1
    stop = stop or threading.Event()
    watcher = LockWatcher(lock_query)
    listener = None
    daemon = None
    previous: dict[int, object] = {}
    try:
        from Xlib.error import ConnectionClosedError

        from logitech_lighting.devices.g815.keys import XInputTooOld, XKeySource

        try:
            keys = (make_keys or XKeySource)()
        except XInputTooOld as exc:
            log.error("%s", exc)
            return 1
        listener = bind_socket(rt / SOCKET_NAME)
        daemon = Daemon(make_connector(), keys, lambda: watcher.locked,
                        StateFile(state_path or default_state_path()))
        watcher.locked = lock_query()
        watcher.start()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
        log.info("wave daemon started (preset %s, %s)", daemon.preset, "off" if daemon.off else "on")
        try:
            serve(daemon, listener, stop, wake_fd=keys.fileno() if hasattr(keys, "fileno") else None)
        except ConnectionClosedError:
            log.info("X session closed; exiting")
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        watcher.stop()
        if daemon is not None:
            daemon.shutdown()
        if listener is not None:
            listener.close()
            (rt / SOCKET_NAME).unlink(missing_ok=True)
        os.close(lock_fd)
```

- [ ] **Step 4: Write `wave_cli.py`**

`g560ctl/src/logitech_lighting/devices/g815/wave_cli.py`:

```python
"""`logitech-lighting wave red|blue|off|status|daemon`: a thin client of the wave daemon."""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

NOT_RUNNING = "wave daemon not running — start it with: systemctl --user start g815-wave"


class DaemonNotRunning(Exception):
    pass


def send_command(req: dict, path: Path | None = None, timeout: float = 3.0) -> dict:
    from logitech_lighting.devices.g815.daemon import socket_path

    path = path or socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise DaemonNotRunning(str(exc)) from exc
        sock.sendall(json.dumps(req).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data)


def format_status(reply: dict) -> str:
    lines = [
        f"preset:   {reply['preset']}",
        f"state:    {reply['state']}",
        f"keyboard: {'connected' if reply['connected'] else 'not connected'}",
        f"fps:      {reply['fps']} (last burst of frames)",
    ]
    if reply.get("lock") == "unknown":
        lines.append("lock state unknown — rings stay paused until GNOME ScreenSaver answers")
    return "\n".join(lines)


def run_wave(action: str, path: Path | None = None) -> int:
    if action == "daemon":
        from logitech_lighting.devices.g815.daemon import run_daemon

        return run_daemon()
    if action == "status":
        req = {"cmd": "status"}
    elif action == "off":
        req = {"cmd": "off"}
    else:
        req = {"cmd": "preset", "name": action}
    try:
        reply = send_command(req, path)
    except DaemonNotRunning:
        print(NOT_RUNNING, file=sys.stderr)
        return 1
    except (socket.timeout, ValueError) as exc:
        print(f"Error: wave daemon did not answer ({exc})", file=sys.stderr)
        return 1
    if not reply.get("ok"):
        print(f"Error: {reply.get('error')}", file=sys.stderr)
        return 1
    print(format_status(reply))
    return 0
```

- [ ] **Step 5: Wire `wave` into `cli.py`**

In `g560ctl/src/logitech_lighting/cli.py`, `build_parser()`, right after the TUI subparser block (`p_tui.set_defaults(func="tui")`), add:

```python

    # G815 keyboard ripple (talks to the g815-wave daemon; never touches the G560)
    p_wave = sub.add_parser("wave", help="G815 keyboard ripple: red, blue, off, status, daemon")
    p_wave.add_argument("action", choices=["red", "blue", "off", "status", "daemon"])
    p_wave.set_defaults(func="wave")
```

In `main()`, right after the `list_devices` branch (`print_devices()` / `return 0`) and **before** `device_id = args.device or get_default_device()`, add:

```python

        # G815 wave: dispatched before any G560 setup
        if args.func == "wave":
            from logitech_lighting.devices.g815.wave_cli import run_wave
            return run_wave(args.action)
```

- [ ] **Step 6: Run the tests and see them pass**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test/test_new_g815_service.py -q`
Expected: `8 passed`

- [ ] **Step 7: Run the full suite, check the CLI, commit**

Run: `g560ctl/.venv/bin/python -m pytest g560ctl/test -q`
Expected: `146 passed`

Run: `./lights wave status; echo "exit=$?"`
Expected: `wave daemon not running — start it with: systemctl --user start g815-wave` and `exit=1`.

Run: `./lights list-zones | head -2`
Expected: the G560 zone listing, unchanged.

```bash
git add g560ctl/src/logitech_lighting/devices/g815/daemon.py g560ctl/src/logitech_lighting/devices/g815/wave_cli.py g560ctl/src/logitech_lighting/cli.py g560ctl/test/test_new_g815_service.py
git commit -m "feat(g815): wave daemon service plumbing and 'wave' CLI subcommand"
```

---

### Task 7: systemd unit, docs, install and hardware checks (with the user)

**Files:**
- Create: `systemd/g815-wave.service`
- Modify: `CLAUDE.md` (a new "G815 keyboard wave" section)

**Interfaces:**
- **Consumes:** `./lights wave daemon` (Task 6).
- **Produces:** the installed, running user service, and the recorded hardware results.

- [ ] **Step 1: Write the unit file**

`systemd/g815-wave.service`:

```ini
# G815 keypress ripple daemon. Install (one time):
#   install -Dm644 systemd/g815-wave.service ~/.config/systemd/user/g815-wave.service
#   systemctl --user daemon-reload && systemctl --user enable --now g815-wave
[Unit]
Description=Logitech G815 keypress ripple lighting
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=%h/Documents/personal/pc_tweaks/speakers_ligth/lights wave daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
```

- [ ] **Step 2: Document it in `CLAUDE.md`**

Insert this section right before `## Why the \`sg\` wrapper`:

````markdown
## G815 keyboard wave (keypress ripple)

The **Logitech G815** keyboard (`046d:c33f`) gets a reactive effect: every key
press sends a ring of light across the keyboard over a dark indigo base
(`#140028`). A systemd **user** service, `g815-wave`, runs it from login. Switch
it from anywhere:

| Command | Effect |
| --- | --- |
| `ligths wave red` | red rings (white → red → magenta) |
| `ligths wave blue` | light-blue rings (white → cyan → blue) |
| `ligths wave off` | hand the keyboard back to its onboard lighting (stays off across replug and reboot) |
| `ligths wave status` | preset, state, keyboard connected, fps of the last burst of frames |

- **States:**
  - `off`: you chose off.
  - `disconnected`: keyboard absent; it is polled every 2 s.
  - `locked`: screen locked or lock state unknown; base color only, no rings.
  - `active`: rings live.
- **Choice storage:** your choice is kept in `~/.config/logitech-lighting/wave.json`.
- **Code and design:**
  - Code: `g560ctl/src/logitech_lighting/devices/g815/`.
  - Design and hardware findings: `docs/superpowers/specs/2026-10-13-g815-wave-design.md`.
- **Install (one-time, already done on this machine):**

  ```bash
  install -Dm644 systemd/g815-wave.service ~/.config/systemd/user/g815-wave.service
  systemctl --user daemon-reload
  systemctl --user enable --now g815-wave
  ```

- **Access:** the HID++ node is opened through the `logitech-lighting` group. The
  Phase 1 udev rule `experiments/99-logitech-g815.rules` grants it for interface 1
  only. Key presses come from X11 (XInput2), so the `input` group is not needed.
- **Troubleshooting:**
  - `wave daemon not running` → `systemctl --user start g815-wave`.
  - Logs → `journalctl --user -u g815-wave -n 50`.
  - The journal says DISPLAY/XAUTHORITY are missing → `systemctl --user import-environment DISPLAY XAUTHORITY`, then `systemctl --user restart g815-wave`.
  - Leftover ripple colors after the daemon was killed hard → press **M1**, which re-selects the onboard profile.
````

- [ ] **Step 3: Commit**

```bash
git add systemd/g815-wave.service CLAUDE.md
git commit -m "feat(g815): systemd user unit and docs for the wave daemon"
```

- [ ] **Step 4: Foreground smoke run (needs the user watching the keyboard)**

Run, in the background: `./lights wave daemon`.
Then ask the user to type for a few seconds. In a second shell, run `./lights wave status`.
Expected:
- the keyboard turns base indigo `#140028`, and typing makes red rings;
- `state: active`, `keyboard: connected`, and `fps` ≥ 30 right after typing.

Run `./lights wave blue`: rings turn blue. Then stop the daemon (`kill %1` or SIGTERM). Expected: the keyboard returns to its onboard effect, and `$XDG_RUNTIME_DIR/g815-wave.sock` is gone.

- [ ] **Step 5: Install and enable the service (ask the user first; it changes their login session)**

```bash
install -Dm644 systemd/g815-wave.service ~/.config/systemd/user/g815-wave.service
systemctl --user daemon-reload
systemctl --user enable --now g815-wave
systemctl --user status g815-wave --no-pager | head -5
```

Expected: `active (running)`. If the journal (`journalctl --user -u g815-wave -n 20`) shows the DISPLAY/XAUTHORITY hint, run `systemctl --user import-environment DISPLAY XAUTHORITY`, then `systemctl --user restart g815-wave`.

- [ ] **Step 6: Hardware checks by eye (spec "Hardware checks" 2-9), with the user**

Ask the user, one at a time, and record each answer:
1. Ripple with `ligths wave red` and `ligths wave blue`, typing slow and fast.
2. `ligths wave off`: the onboard lighting returns. Unplug and replug while OFF: it stays on onboard lighting. `ligths wave red` resumes.
3. Lock the screen (Super+L): rings stop within about 1 s and the keyboard shows base. Unlock: rings resume.
4. Unplug and replug while ACTIVE: within about 2 s of replugging, the keyboard returns to base and rings work.
5. Suspend and resume: within about 10 s the keyboard is back under wave control.
6. Log out and in: the service stops and starts with the session (`systemctl --user status g815-wave`).
7. `ligths wave status` right after typing shows fps ≥ 30.
8. `ligths solid 0000ff --zones primary` still drives the G560.

If a check fails, use superpowers:systematic-debugging. Record each fix as a ruling in the ledger.

- [ ] **Step 7: Record the results in the spec and commit**

Append to `docs/superpowers/specs/2026-10-13-g815-wave-design.md`:

```markdown
## Hardware check results (Part 2)

- Ripple red/blue, slow/fast: …
- wave off / replug while OFF / wave red: …
- Lock / unlock: …
- Replug while ACTIVE: …
- Suspend / resume: …
- Logout / login: …
- wave status fps after typing: …
- G560 unaffected: …
```

Replace every `…` with the observed result. Then:

```bash
git add docs/superpowers/specs/2026-10-13-g815-wave-design.md
git commit -m "docs: G815 wave Part 2 hardware check results"
```
