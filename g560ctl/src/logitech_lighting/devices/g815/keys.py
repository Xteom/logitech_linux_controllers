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
