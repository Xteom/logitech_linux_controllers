"""G815 semantics on top of hidpp.Sender: discovery, claim/release, frames, control checks.

Byte sequences verified on hardware in Gate A (see the spec's "Gate A results"):
  claim    0x8071 fn5 [01 03 04], 0x8100 fn1 [02], 0x8081 fn0 [00 page 00] for pages 0-2
  release  0x8071 fn5 [01 00 00], 0x8100 fn1 [01], 0x8100 fn4 -> profile, 0x8100 fn3 [profile]
  G-keys   0x8010 fn2 [01] diverts them (Solaar "Divert G and M Keys"); each change then arrives
           as a notification `11 ff <gkey idx> 00 <bitmask>` (G1 = bit 0 ... G5 = bit 4); [00] undoes it
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from logitech_lighting.devices.g815.frame import FN_SET_INDIVIDUAL, FN_SET_RANGE, Write, encode
from logitech_lighting.devices.g815.hidpp import DeviceGone, Port, Reply, RequestFailed, Sender
from logitech_lighting.devices.g815.layout import BY_ZONE
from logitech_lighting.devices.g815.presets import Color

log = logging.getLogger(__name__)

VID, PID = 0x046D, 0xC33F
USAGE_PAGE, USAGE = 0xFF43, 0x0602

ROOT = 0x00
PERKEY, EFFECTS, ONBOARD, GKEY = 0x8081, 0x8071, 0x8100, 0x8010
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
        self.applied: set[str] = set()          # "sw" (SetSWControl), "host" (mode 02), "gkeys" (diverted)
        self.valid: frozenset[int] = frozenset()
        self.confirmed: dict[int, Color] | None = None
        self.abandoned = 0                      # consecutive abandoned frames
        self.committed = 0                      # frames acknowledged by frameEnd
        self._gmask = 0
        self._gkeys: list[str] = []
        sender.on_notify = self._on_notify

    @property
    def needs_reclaim(self) -> bool:
        return self.abandoned >= MAX_ABANDONED

    def discover(self) -> dict[int, int]:
        self.idx = {}
        for fid in (PERKEY, EFFECTS, ONBOARD, GKEY):
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
            if GKEY in self.idx:
                self.sender.request(self.idx[GKEY], 2, b"\x01")
                self.applied.add("gkeys")
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
        except DeviceGone as exc:
            if not exc.io_error:            # still reachable (e.g. ids ran out): don't leave host mode on
                self.release()
            raise
        self.abandoned = 0

    def _undo(self) -> None:
        """Best effort, only what the claim applied, in the order verified in Gate A. A failed
        step does not stop the later ones; DeviceGone (nothing left to talk to) does."""
        steps = []
        if "gkeys" in self.applied:
            steps.append(("G-key undivert", lambda: self.sender.request(self.idx[GKEY], 2, b"\x00")))
        if "sw" in self.applied:
            steps.append(("SW control off", lambda: self.sender.request(self.idx[EFFECTS], 5, SW_RELEASE)))
        if "host" in self.applied:
            steps.append(("onboard mode", lambda: self.sender.request(self.idx[ONBOARD], 1, bytes([MODE_ONBOARD]))))
            steps.append(("profile reselect", self._reselect_profile))   # makes the onboard effect reappear
        try:
            for name, step in steps:
                try:
                    step()
                except RequestFailed as exc:
                    log.warning("release step %s failed: %s", name, exc)
        finally:
            self.applied = set()
            self.confirmed = None

    def _reselect_profile(self) -> None:
        profile = self.sender.request(self.idx[ONBOARD], 4)[:2]
        self.sender.request(self.idx[ONBOARD], 3, profile)

    def release(self) -> None:
        try:
            self._undo()
        except DeviceGone as exc:
            log.warning("keyboard gone during release: %s", exc)

    def send_frame(self, frame: dict[int, Color], resync: tuple[int, ...] = ()) -> bool:
        """Send the changed zones, then frameEnd. True when the frame is committed (or empty)."""
        # Resync zones ride only on frames that already change something: an idle keyboard
        # gets no traffic (the 10 s full repaint covers drift while idle).
        if not encode(self.confirmed, frame, self.valid):
            return True
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

    def _on_notify(self, r: Reply) -> None:
        if GKEY in self.idx and r.feat == self.idx[GKEY]:
            mask = r.params[0]
            pressed = mask & ~self._gmask
            self._gmask = mask
            self._gkeys += [f"g{bit + 1}" for bit in range(5) if pressed >> bit & 1]

    def poll_keys(self) -> list[str]:
        """G-key presses (as layout names g1..g5) since the last call."""
        self.sender.poll()
        keys, self._gkeys = self._gkeys, []
        return keys

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
